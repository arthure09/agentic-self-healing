#!/usr/bin/env python3
"""Jalankan batch benchmark (Stage 10). Satu batch = satu model.

    benchmark/run.py --batch NAMA --model qwen|gemini [--levels noob,medium,pro]
                     [--tcs tc01,tc02,tc03,tc04] [--reps 10] [--seed N]

Urutan run diacak sekali (seed disimpan) di benchmark/runs/batches/NAMA/plan.json.
Menjalankan ulang perintah yang sama melanjutkan batch: run yang sudah punya
results/<key>.json dilewati; run yang terhenti di tengah diulang dengan RUN_ID baru.

Satu run:
  1. gateway OpenClaw dan alert-bridge sehat, model agent = model batch
  2. PROMPT_LEVEL di .env + alert-bridge (dibuat ulang bila level berubah)
  3. scripts/reset-env.sh (RUN_ID run ini; mencatat run_config)
  4. jeda stabilisasi 60 s
  5. suntik chaos
  6. tunggu alert padam (Prometheus ALERTS kosong) atau batas 10 menit
  7. tunggu semua sesi agent selesai (maks. 5 menit lagi), lalu snapshot kondisi nyata
  8. hentikan chaos, tulis event run_end, kumpulkan data mentah, simpan hasil
Metrik dihitung terpisah oleh benchmark/analyze.py dari results/*.json.
PROMPT_LEVEL di .env dikembalikan ke nilai awal dan stack di-reset di akhir batch,
juga bila dihentikan dengan SIGTERM (tombol Hentikan di benchmark/web.py) atau Ctrl+C.
"""
import argparse
import json
import os
import random
import re
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_usage import DB, event_json, jsonl, usage  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "benchmark" / "runs"
PROM = "http://127.0.0.1:9090"
BRIDGE = "http://127.0.0.1:5001/health"
MODELS = {"qwen": "openrouter/qwen/qwen3.7-plus", "gemini": "openrouter/google/gemini-3.8-flash"}
CHAOS = {"tc01": "tc01_connection_pool_exhaustion.py", "tc02": "tc02_deadlock_simulation.py",
         "tc03": "tc03_redis_memory_flood.py", "tc04": "tc04_container_kill.py"}
STABILIZE_S, ALERT_TIMEOUT_S, AGENT_TIMEOUT_S, POLL_S = 60, 600, 300, 2
CONTAINERS = ["medusa-app", "medusa-postgres", "medusa-redis"]
SNAPSHOT_QUERIES = {
    "pg_conn_ratio": "sum(pg_stat_activity_count) / scalar(pg_settings_max_connections)",
    "redis_mem_ratio": "redis_memory_used_bytes / redis_memory_max_bytes",
    "pg_up": "min(pg_up)", "redis_up": "min(redis_up)",
}


def ms() -> int:
    return int(time.time() * 1000)


def log(*a) -> None:
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)


STATUS: dict = {}  # tahap yang sedang berjalan, dibaca benchmark/web.py


def phase(name: str, **kw) -> None:
    if name == "reset":  # run baru: buang data run sebelumnya
        for k in ("inject_ms", "alert_fired_ms", "alert_cleared"):
            STATUS.pop(k, None)
    if name != STATUS.get("phase"):
        STATUS["phase_started_ms"] = ms()
    STATUS["expected_s"] = kw.pop("expected_s", None)  # perkiraan/batas lama tahap ini
    STATUS.update(kw, phase=name)
    if STATUS.get("file"):
        Path(STATUS["file"]).write_text(json.dumps(STATUS))


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.load(r)


def prom(q: str) -> list:
    return get_json(f"{PROM}/api/v1/query?query={urllib.parse.quote(q)}")["data"]["result"]


def event(run_id: str, scenario: str, name: str, **extra) -> None:
    with open(RUNS / "events.jsonl", "a") as f:
        f.write(json.dumps({"ts_ms": ms(), "run_id": run_id, "scenario": scenario, "event": name,
                            "host": os.uname().nodename, **extra}) + "\n")


def sh(*cmd, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, check=True, text=True, **kw)


def git_state() -> dict:
    head = sh("git", "rev-parse", "HEAD", capture_output=True).stdout.strip()
    dirty = sh("git", "status", "--porcelain", "--untracked-files=no", capture_output=True).stdout.strip()
    return {"commit": head, "dirty": bool(dirty)}


def env_level() -> str:
    m = re.search(r"(?m)^PROMPT_LEVEL=(.*)$", (ROOT / ".env").read_text())
    return m.group(1).strip() if m else ""


def set_level(level: str) -> None:
    env = ROOT / ".env"
    env.write_text(re.sub(r"(?m)^PROMPT_LEVEL=.*$", f"PROMPT_LEVEL={level}", env.read_text()))
    if get_json(BRIDGE).get("prompt_level") == level:
        return
    sh("docker", "compose", "up", "-d", "alert-bridge", capture_output=True)
    for _ in range(30):
        time.sleep(2)
        try:
            if get_json(BRIDGE).get("prompt_level") == level:
                return
        except OSError:
            pass
    raise RuntimeError(f"alert-bridge tidak siap dengan PROMPT_LEVEL={level}")


def check_health(model: str) -> None:
    gw = subprocess.run(["systemctl", "--user", "is-active", "openclaw-gateway"], capture_output=True, text=True)
    if gw.stdout.strip() != "active":
        raise RuntimeError("openclaw-gateway tidak aktif")
    h = get_json(BRIDGE)
    if h.get("status") != "ok" or not h.get("forward_configured") or h.get("agent_id") != "merapi":
        raise RuntimeError(f"alert-bridge tidak sehat: {h}")
    oc = json.loads((Path.home() / ".openclaw" / "openclaw.json").read_text())
    got = (oc["agents"]["entries"]["merapi"].get("model") or {}).get("primary")
    if got != MODELS[model]:
        raise RuntimeError(f"model agent merapi = {got}, batch memakai {MODELS[model]}")


def sessions_since(c, t0: int) -> list[tuple]:
    return c.execute("select session_id, session_key, status, created_at from session_windows "
                     "where created_at >= ? order by created_at", (t0,)).fetchall()


def transcript(c, sid: str) -> dict:
    """Pemanggilan tool berurutan (termasuk yang ditolak) dan teks akhir agent."""
    calls, results, texts = [], {}, []
    for j, z in c.execute("select event_json, event_zstd from transcript_events where session_id=? order by seq", (sid,)):
        m = event_json(j, z).get("message") or {}
        if m.get("role") == "assistant":
            parts = [p for p in m.get("content", []) if isinstance(p, dict)]
            texts.append("".join(p.get("text", "") for p in parts if p.get("type") == "text"))
            for p in parts:
                if p.get("type") == "toolCall":
                    a = p.get("arguments") or {}
                    calls.append({"id": p.get("id"), "ts_ms": m.get("timestamp"), "tool": p.get("name"),
                                  "arg": a.get("command") or a.get("path") or json.dumps(a, ensure_ascii=False)})
        elif m.get("role") == "toolResult":
            d = m.get("details") or {}
            results[m.get("toolCallId")] = {"is_error": bool(m.get("isError")), "error": d.get("error")}
    for call in calls:
        r = results.get(call.pop("id"), {})
        call["is_error"] = r.get("is_error", False)
        call["denied"] = "denied" in str(r.get("error") or "")
    final = next((t for t in reversed(texts) if t.strip()), "")
    return {"calls": calls, "final": final}


def snapshot() -> dict:
    states = subprocess.run(["docker", "inspect", "-f", "{{.Name}}|{{.State.Status}}|"
                             "{{if .State.Health}}{{.State.Health.Status}}{{end}}|{{.RestartCount}}", *CONTAINERS],
                            capture_output=True, text=True).stdout.split()
    containers = {}
    for line in states:
        name, status, health, restarts = line.lstrip("/").split("|")
        containers[name] = {"status": status, "health": health, "restarts": int(restarts)}
    metrics = {}
    for k, q in SNAPSHOT_QUERIES.items():
        r = prom(q)
        metrics[k] = float(r[0]["value"][1]) if r else None
    return {"ts_ms": ms(), "alerts": sorted({a["metric"].get("alertname", "") for a in prom("ALERTS")}),
            "containers": containers, "metrics": metrics}


def one_run(key: str, spec: dict, model: str, out: Path) -> None:
    tc, level = spec["tc"], spec["level"]
    run_id = f"{key}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    started = ms()
    phase("reset", key=key, run_id=run_id, level=level, tc=tc, rep=spec["rep"], run_started_ms=started)
    check_health(model)
    set_level(level)
    env = {**os.environ, "RUN_ID": run_id}
    sh("scripts/reset-env.sh", env=env)
    log(f"{run_id}: reset selesai, stabilisasi {STABILIZE_S} s")
    phase("stabilisasi", expected_s=STABILIZE_S)
    time.sleep(STABILIZE_S)

    inject = ms()
    chaos_log = open(out / f"{key}.chaos.log", "w")
    chaos = subprocess.Popen([str(ROOT / ".venv/bin/python"), str(ROOT / "chaos" / CHAOS[tc])],
                             cwd=ROOT, env=env, stdout=chaos_log, stderr=subprocess.STDOUT)
    log(f"{run_id}: chaos {tc} disuntik (level {level})")
    phase("menunggu alert padam", expected_s=ALERT_TIMEOUT_S, inject_ms=inject)

    c = sqlite3.connect(f"file:{str(DB).format(agent='merapi')}?mode=ro", uri=True)
    fired_ms = clear_ms = None
    while ms() < inject + ALERT_TIMEOUT_S * 1000:
        time.sleep(POLL_S)
        active = prom("ALERTS")
        if active and not fired_ms:
            fired_ms = ms()
            phase("menunggu alert padam", expected_s=ALERT_TIMEOUT_S, alert_fired_ms=fired_ms)
        if fired_ms and not active:
            clear_ms = ms()
            break
    log(f"{run_id}: alert {'padam' if clear_ms else 'tidak padam / tidak muncul'}; menunggu agent")
    phase("menunggu agent", expected_s=AGENT_TIMEOUT_S, alert_cleared=bool(clear_ms))
    agent_deadline = ms() + AGENT_TIMEOUT_S * 1000
    while True:
        sess = sessions_since(c, inject)
        done = sess and all(s[2] != "running" for s in sess)
        if done or ms() > agent_deadline:
            break
        time.sleep(POLL_S)
    agent_done_ms = ms()
    phase("menyimpan")
    snap = snapshot()

    chaos.terminate()
    try:
        chaos.wait(15)
    except subprocess.TimeoutExpired:
        chaos.kill()
    chaos_log.close()
    event(run_id, tc, "run_end")

    events = [e for e in jsonl(RUNS / "events.jsonl") if e.get("run_id") == run_id]
    result = {
        "key": key, "run_id": run_id, **spec, "model": model, "model_ref": MODELS[model],
        "started_ms": started, "inject_ms": inject, "git": git_state(),
        "run_config": next((e for e in events if e.get("event") == "run_config"), {}),
        "prom_first_alert_ms": fired_ms, "prom_clear_ms": clear_ms,
        "agent_done_ms": agent_done_ms, "agent_timeout": not done,
        "snapshot_end": snap,
        "chaos_events": [e for e in events if e.get("scenario") == tc],
        "alerts": [a for a in jsonl(RUNS / "alerts.jsonl") if a.get("bridge_received_ms", 0) >= inject],
        "actions": [a for a in jsonl(RUNS / "actions.jsonl") if inject <= a["ts_ms"] <= agent_done_ms],
        "sessions": [{"session_id": s[0], "session_key": s[1], "status": s[2], "created_ms": s[3],
                      **transcript(c, s[0])} for s in sess],
        "usage": usage(run_id),
    }
    (out / "results" / f"{key}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    u = result["usage"]
    log(f"{run_id}: selesai; sesi {u['sessions']}, biaya ${u['cost_usd']}, alert padam {bool(clear_ms)}")


def main():
    ap = argparse.ArgumentParser(description="Batch benchmark agent (Stage 10)")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--model", required=True, choices=sorted(MODELS))
    ap.add_argument("--levels", default="noob,medium,pro")
    ap.add_argument("--tcs", default="tc01,tc02,tc03,tc04")
    ap.add_argument("--reps", type=int, default=10)
    ap.add_argument("--seed", type=int)
    a = ap.parse_args()

    out = RUNS / "batches" / a.batch
    (out / "results").mkdir(parents=True, exist_ok=True)
    plan_file = out / "plan.json"
    if plan_file.exists():
        plan = json.loads(plan_file.read_text())
        if plan["model"] != a.model:
            sys.exit(f"batch {a.batch} memakai model {plan['model']}, bukan {a.model}")
        log(f"melanjutkan batch {a.batch} (seed {plan['seed']})")
    else:
        levels, tcs = a.levels.split(","), a.tcs.split(",")
        if not set(levels) <= {"noob", "medium", "pro"} or not set(tcs) <= set(CHAOS):
            sys.exit("level/TC tidak dikenal")
        seed = a.seed if a.seed is not None else random.SystemRandom().randrange(2**31)
        runs = [{"level": lv, "tc": tc, "rep": r} for lv in levels for tc in tcs for r in range(1, a.reps + 1)]
        random.Random(seed).shuffle(runs)
        for i, r in enumerate(runs, 1):
            r["key"] = f"{a.batch}-{i:03d}-{a.model}-{r['level']}-{r['tc']}-r{r['rep']:02d}"
        plan = {"batch": a.batch, "model": a.model, "model_ref": MODELS[a.model], "seed": seed,
                "created_ms": ms(), "git": git_state(), "runs": runs}
        plan_file.write_text(json.dumps(plan, indent=1))
        log(f"batch baru {a.batch}: {len(runs)} run, seed {seed}")

    # SIGTERM -> SystemExit, supaya blok finally (kembalikan level + reset) tetap jalan
    signal.signal(signal.SIGTERM, lambda *_: sys.exit("dihentikan (SIGTERM)"))
    original_level = env_level()
    STATUS.update(file=str(out / "status.json"), batch=a.batch, total=len(plan["runs"]))
    sh("scripts/set-model.sh", a.model)
    try:
        for i, r in enumerate(plan["runs"], 1):
            if (out / "results" / f"{r['key']}.json").exists():
                continue
            STATUS["index"] = i
            one_run(r["key"], {k: r[k] for k in ("level", "tc", "rep")}, a.model, out)
    finally:
        phase("reset penutup", expected_s=45)
        set_level(original_level)
        sh("scripts/reset-env.sh", env={**os.environ, "RUN_ID": f"{a.batch}-closing-reset"})
        phase("selesai")
    done = sum((out / "results" / f"{r['key']}.json").exists() for r in plan["runs"])
    log(f"batch {a.batch}: {done}/{len(plan['runs'])} run selesai")


if __name__ == "__main__":
    main()
