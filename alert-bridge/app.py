"""alert-bridge: webhook Alertmanager -> log JSONL + OpenClaw hook.

Menerima webhook Alertmanager (POST /alertmanager), mencatat setiap alert
(firing maupun resolved) ke JSONL dengan timestamp diterima bridge dalam epoch
milidetik, lalu meneruskan alert firing ke OpenClaw lewat POST /hooks/agent.

- Webhook langsung dibalas 200; setiap alert diteruskan di thread sendiri agar
  Alertmanager tidak menunggu OpenClaw dan alert yang datang bersamaan (mis.
  PostgresDown + RedisDown pada TC-04) tidak saling mengantre.
- Alertmanager mengirim ulang alert yang sama setiap group_interval. Alert
  diteruskan sekali per (fingerprint, startsAt); pengiriman ulang tetap dicatat
  dengan first_seen=false.
- Satu gangguan = satu run agent: alert baru dari skenario yang masih punya
  alert aktif (mis. RedisDown menyusul PostgresDown pada TC-04) tidak
  diteruskan lagi, hanya dicatat sebagai forward_merged.
- Pesan ke agent diambil dari template prompts/<PROMPT_LEVEL>/<scenario>.txt
  (noob, medium, pro). Placeholder {alertname}, {severity}, {starts_at},
  {summary}, {description} diisi dari data alert.
- OpenClaw belum ada, token kosong, atau request gagal: dicatat sebagai event
  forward_skipped / forward_failed, tanpa membuat bridge crash.

Hanya memakai pustaka standar Python.
"""
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOOK_URL = os.environ.get("OPENCLAW_HOOK_URL", "")
HOOK_TOKEN = os.environ.get("OPENCLAW_HOOK_TOKEN", "")
AGENT_ID = os.environ.get("OPENCLAW_AGENT_ID", "main")
LOG_FILE = os.environ.get("ALERT_LOG_FILE", "/data/alerts.jsonl")
PORT = int(os.environ.get("PORT", "5001"))
RETRIES = int(os.environ.get("FORWARD_RETRIES", "3"))
TIMEOUT_S = float(os.environ.get("FORWARD_TIMEOUT_S", "10"))
PROMPT_DIR = os.environ.get("PROMPT_DIR", "/prompts")
PROMPT_LEVEL = os.environ.get("PROMPT_LEVEL", "pro")
MERGE_WINDOW_S = int(os.environ.get("MERGE_WINDOW_S", "300"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("alert-bridge")

_write_lock = threading.Lock()
_seen: set[tuple[str, str]] = set()
_seen_lock = threading.Lock()
# scenario -> (fingerprint alert aktif, ms run terakhir diteruskan, alertname pemicu)
_active: dict[str, tuple[set[str], int, str]] = {}
_in_flight = 0
_stats_lock = threading.Lock()
_stats = {"received": 0, "forward_ok": 0, "forward_failed": 0, "forward_skipped": 0}
_started_ms = time.time_ns() // 1_000_000


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def to_ms(rfc3339: str) -> int | None:
    if not rfc3339 or rfc3339.startswith("0001-"):
        return None
    return int(datetime.fromisoformat(rfc3339.replace("Z", "+00:00")).timestamp() * 1000)


def record(event: str, **data) -> None:
    line = json.dumps({"event": event, **data}, ensure_ascii=False)
    with _write_lock, open(LOG_FILE, "a") as f:
        f.write(line + "\n")
    log.info(line)


def forward_configured() -> bool:
    return bool(HOOK_URL) and bool(HOOK_TOKEN) and HOOK_TOKEN != "CHANGE_ME"


class _Keep(dict):
    def __missing__(self, key):  # placeholder tak dikenal dibiarkan apa adanya
        return "{" + key + "}"


def build_message(alert: dict) -> tuple[str, str]:
    """(pesan, file template). Label scenario tidak pernah ikut dikirim ke agent."""
    labels, ann = alert.get("labels", {}), alert.get("annotations", {})
    fields = _Keep(alertname=labels.get("alertname", ""), severity=labels.get("severity", ""),
                   starts_at=alert.get("startsAt", ""), summary=ann.get("summary", ""),
                   description=ann.get("description", ""))
    path = os.path.join(PROMPT_DIR, PROMPT_LEVEL, f"{labels.get('scenario', '')}.txt")
    try:
        with open(path) as f:
            return f.read().strip().format_map(fields), path
    except OSError:  # skenario tanpa template: pesan netral, tanpa petunjuk
        return f"Alert {fields['alertname']}: {fields['summary']}. {fields['description']}", "-"


def claim_run(alert: dict, scenario: str | None, now: int) -> str | None:
    """Catat alert firing; kembalikan alertname pemicu run aktif bila alert ini cukup digabung."""
    if not scenario:
        return None
    fp = alert.get("fingerprint", "")
    with _seen_lock:
        fps, last_ms, trigger = _active.get(scenario, (set(), 0, ""))
        if fps and now - last_ms < MERGE_WINDOW_S * 1000:
            fps.add(fp)
            return trigger
        _active[scenario] = ({fp}, now, alert.get("labels", {}).get("alertname", ""))
        return None


def release(alert: dict, scenario: str | None) -> None:
    with _seen_lock:
        if scenario in _active:
            _active[scenario][0].discard(alert.get("fingerprint", ""))
            if not _active[scenario][0]:
                del _active[scenario]


def bump(key: str, delta: int = 1) -> None:
    global _in_flight
    with _stats_lock:
        if key == "in_flight":
            _in_flight += delta
        else:
            _stats[key] += delta


def forward(alert: dict, base: dict) -> None:
    bump("in_flight")
    try:
        _forward(alert, base)
    finally:
        bump("in_flight", -1)


def _forward(alert: dict, base: dict) -> None:
    if not forward_configured():
        bump("forward_skipped")
        record("forward_skipped", **base, reason="OPENCLAW_HOOK_URL/TOKEN belum dikonfigurasi")
        return
    message, template = build_message(alert)
    # Nama tugas netral dan sama untuk semua level: OpenClaw menampilkannya ke agent
    # ("Task: ..."), jadi alertname di sini akan bocor ke level noob.
    base = {**base, "prompt_level": PROMPT_LEVEL, "prompt_file": template,
            "task_name": f"laporan-{uuid.uuid4().hex[:8]}"}
    body = json.dumps({
        "message": message,
        "agentId": AGENT_ID,
        "name": base["task_name"],
        "deliver": False,  # hasil cukup di sesi run; True memicu putaran tambahan di sesi main
    }).encode()
    last_error = None
    for attempt in range(1, RETRIES + 1):
        sent_ms = now_ms()
        req = urllib.request.Request(HOOK_URL, data=body, method="POST", headers={
            "Authorization": f"Bearer {HOOK_TOKEN}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                bump("forward_ok")
                record("forward_ok", **base, attempt=attempt, forward_sent_ms=sent_ms,
                       forward_done_ms=now_ms(), http_status=resp.status,
                       response=resp.read(500).decode(errors="replace"))
                break
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}: {e.read(300).decode(errors='replace')}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = f"{type(e).__name__}: {getattr(e, 'reason', e)}"
        if attempt < RETRIES:
            time.sleep(2 ** (attempt - 1))
    else:
        bump("forward_failed")
        record("forward_failed", **base, attempts=RETRIES, error=last_error,
               gave_up_ms=now_ms())


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._reply(200, {"status": "ok", "forward_configured": forward_configured(),
                              "hook_url": HOOK_URL, "agent_id": AGENT_ID,
                              "prompt_level": PROMPT_LEVEL,
                              "uptime_s": (now_ms() - _started_ms) // 1000,
                              "in_flight": _in_flight, **_stats})
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/alertmanager":
            return self._reply(404, {"error": "not found"})
        received_ms = now_ms()
        try:
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except (ValueError, json.JSONDecodeError):
            return self._reply(400, {"error": "invalid JSON"})

        for alert in payload.get("alerts", []):
            labels = alert.get("labels", {})
            key = (alert.get("fingerprint", ""), alert.get("startsAt", ""))
            with _seen_lock:
                first_seen = alert.get("status") == "firing" and key not in _seen
                if first_seen:
                    _seen.add(key)
            starts_ms = to_ms(alert.get("startsAt", ""))
            base = {
                "bridge_received_ms": received_ms,
                "status": alert.get("status"),
                "alertname": labels.get("alertname"),
                "scenario": labels.get("scenario"),
                "severity": labels.get("severity"),
                "fingerprint": alert.get("fingerprint"),
                "starts_at": alert.get("startsAt"),
                "starts_at_ms": starts_ms,
                "ends_at_ms": to_ms(alert.get("endsAt", "")) if alert.get("status") == "resolved" else None,
                "alert_to_bridge_ms": received_ms - starts_ms if starts_ms else None,
            }
            bump("received")
            record("alert_received", **base, first_seen=first_seen,
                   group_key=payload.get("groupKey"), summary=alert.get("annotations", {}).get("summary"))
            if alert.get("status") == "resolved":
                release(alert, labels.get("scenario"))
            if first_seen:
                merged_into = claim_run(alert, labels.get("scenario"), received_ms)
                if merged_into:
                    record("forward_merged", **base, merged_into=merged_into)
                else:
                    threading.Thread(target=forward, args=(alert, base), daemon=True).start()

        self._reply(200, {"ok": True, "alerts": len(payload.get("alerts", []))})

    def log_message(self, fmt, *args):  # akses log bawaan terlalu berisik
        pass


if __name__ == "__main__":
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    if PROMPT_LEVEL not in ("noob", "medium", "pro"):
        raise SystemExit(f"PROMPT_LEVEL harus noob, medium, atau pro (sekarang: {PROMPT_LEVEL!r})")
    log.info("alert-bridge :%d, forward ke %s (terkonfigurasi: %s), prompt level %s",
             PORT, HOOK_URL, forward_configured(), PROMPT_LEVEL)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
