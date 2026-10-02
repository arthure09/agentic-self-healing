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
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOOK_URL = os.environ.get("OPENCLAW_HOOK_URL", "")
HOOK_TOKEN = os.environ.get("OPENCLAW_HOOK_TOKEN", "")
AGENT_ID = os.environ.get("OPENCLAW_AGENT_ID", "main")
LOG_FILE = os.environ.get("ALERT_LOG_FILE", "/data/alerts.jsonl")
PORT = int(os.environ.get("PORT", "5001"))
RETRIES = int(os.environ.get("FORWARD_RETRIES", "3"))
TIMEOUT_S = float(os.environ.get("FORWARD_TIMEOUT_S", "10"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("alert-bridge")

_write_lock = threading.Lock()
_seen: set[tuple[str, str]] = set()
_seen_lock = threading.Lock()
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


def build_message(alert: dict, received_ms: int) -> str:
    labels, ann = alert.get("labels", {}), alert.get("annotations", {})
    received_iso = datetime.fromtimestamp(received_ms / 1000, timezone.utc).isoformat()
    return (
        f"[ALERT FIRING] {labels.get('alertname')} (skenario {labels.get('scenario', '-')}, "
        f"severity {labels.get('severity', '-')})\n"
        f"Ringkasan: {ann.get('summary', '')}\n"
        f"Detail: {ann.get('description', '')}\n"
        f"Alert mulai (Prometheus startsAt): {alert.get('startsAt')}\n"
        f"Diterima alert-bridge: {received_iso} (epoch ms {received_ms})\n"
        f"Fingerprint: {alert.get('fingerprint')}\n\n"
        "Investigasi penyebabnya, lakukan remediasi sesuai skill untuk skenario ini, "
        "lalu verifikasi bahwa layanan kembali normal. Laporkan setiap langkah "
        "(Thought, Action, Observation) dan hasil akhirnya."
    )


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
    body = json.dumps({
        "message": build_message(alert, base["bridge_received_ms"]),
        "agentId": AGENT_ID,
        "name": f"alert-{base['alertname']}",
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
            if first_seen:
                threading.Thread(target=forward, args=(alert, base), daemon=True).start()

        self._reply(200, {"ok": True, "alerts": len(payload.get("alerts", []))})

    def log_message(self, fmt, *args):  # akses log bawaan terlalu berisik
        pass


if __name__ == "__main__":
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    log.info("alert-bridge :%d, forward ke %s (terkonfigurasi: %s)", PORT, HOOK_URL, forward_configured())
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
