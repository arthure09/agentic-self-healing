#!/usr/bin/env python3
"""Token dan biaya agent per run, diambil dari transkrip OpenClaw (bukan perkiraan).

    benchmark/run_usage.py RUN_ID [--append]

Jendela run = event pertama RUN_ID di events.jsonl sampai event run_end (ditulis
benchmark/run.py) atau reset_done kedua (reset penutup); sampai sekarang bila
keduanya tidak ada. Karena itu reset awal, chaos, dan reset penutup memakai RUN_ID
yang sama. Setiap forward_ok alert-bridge di jendela itu
dicocokkan ke sesi agent: dibuat <= 60 s setelah forward dan pesan pertamanya
memuat "Task: <task_name>" (field name hook, dicatat alert-bridge di forward_ok;
sebelum alert-bridge 1.2.0: "Task: alert-<alertname>"). runId di respons hook tidak
tersimpan di database OpenClaw, jadi tidak bisa dipakai untuk mencocokkan.

Per sesi (dijumlahkan dari usage setiap pesan assistant):
  input_new         token input yang ditagih penuh (usage.input)
  input_cache_read  token input dari prompt cache (usage.cacheRead)
  output            token output, termasuk reasoning (usage.output)
  turns             jumlah giliran model (pesan assistant)
  cost_usd          usage.cost.total, dilaporkan OpenRouter (totalOrigin)
  models            provider/model di setiap pesan assistant (harus satu)
  thinking_level    event thinking_level_change sesi (level yang dipakai)
Catatan: angka token Stage 9 di PLAN.md = jumlah input_new saja.
--append menambahkan satu baris ke benchmark/runs/usage.jsonl.
"""
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "benchmark" / "runs"
DB = Path.home() / ".openclaw" / "agents" / "{agent}" / "agent" / "openclaw-agent.sqlite"


def jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def event_json(j, z):
    return json.loads(j if j else subprocess.run(["zstd", "-dc"], input=z, capture_output=True, check=True).stdout)


def session_usage(c, sid):
    u = {"turns": 0, "input_new": 0, "input_cache_read": 0, "cache_write": 0, "output": 0,
         "reasoning": 0, "cost_usd": 0.0, "cost_origin": set(), "response_ids": [],
         "models": set(), "thinking_level": None}
    for j, z in c.execute("select event_json, event_zstd from transcript_events where session_id=? order by seq", (sid,)):
        e = event_json(j, z)
        if e.get("type") == "thinking_level_change":  # level hasil resolusi OpenClaw (bawaan bila tidak di-set)
            u["thinking_level"] = e.get("thinkingLevel")
        m = e.get("message") or {}
        if m.get("role") != "assistant" or not m.get("usage"):
            continue
        us, cost = m["usage"], m["usage"].get("cost") or {}
        u["turns"] += 1
        u["input_new"] += us.get("input", 0)
        u["input_cache_read"] += us.get("cacheRead", 0)
        u["cache_write"] += us.get("cacheWrite", 0)
        u["output"] += us.get("output", 0)
        u["reasoning"] += us.get("reasoningTokens", 0)
        u["cost_usd"] += cost.get("total", 0)
        u["cost_origin"].add(cost.get("totalOrigin", "?"))
        u["response_ids"].append(m.get("responseId"))
        u["models"].add(f"{m.get('provider')}/{m.get('model')}")
    u["cost_origin"] = sorted(u["cost_origin"])
    u["models"] = sorted(u["models"])
    u["cost_usd"] = round(u["cost_usd"], 6)
    return u


def usage(run_id: str) -> dict:
    events = [e for e in jsonl(RUNS / "events.jsonl") if e.get("run_id") == run_id]
    if not events:
        raise SystemExit(f"tidak ada event untuk RUN_ID {run_id}")
    start = min(e["ts_ms"] for e in events)
    resets = [e["ts_ms"] for e in events if e.get("event") == "reset_done"]
    run_end = [e["ts_ms"] for e in events if e.get("event") == "run_end"]
    if run_end:
        end = run_end[-1]
    elif len(resets) >= 2:  # reset awal + reset penutup
        end = resets[-1]
    else:
        end = int(time.time() * 1000)
        print(f"PERINGATAN: {run_id} belum punya run_end/reset penutup; jendela sampai sekarang", file=sys.stderr)
    cfg = next((e for e in events if e.get("event") == "run_config"), {})
    agent = cfg.get("bridge_agent_id") or "merapi"
    c = sqlite3.connect(f"file:{str(DB).format(agent=agent)}?mode=ro", uri=True)

    sessions, unmatched, claimed = [], [], set()
    forwards = [a for a in jsonl(RUNS / "alerts.jsonl")
                if a.get("event") == "forward_ok" and start <= a["forward_sent_ms"] <= end]
    for a in forwards:
        hit = None
        for key, sid, created in c.execute(
                "select session_key, session_id, created_at from session_windows "
                "where created_at between ? and ? order by created_at",
                (a["forward_sent_ms"] - 2000, a["forward_done_ms"] + 60000)):
            first = c.execute("select text from session_transcript_fts where session_id=? and role='user' limit 1",
                              (sid,)).fetchone()
            task = a.get("task_name") or f"alert-{a['alertname']}"  # sebelum alert-bridge 1.2.0
            if first and f"Task: {task}\n" in first[0] and sid not in claimed:
                hit = (key, sid, created)
                claimed.add(sid)
                break
        if not hit:
            unmatched.append(a["alertname"])
            continue
        sessions.append({"alertname": a["alertname"], "session_key": hit[0], "session_id": hit[1],
                         "prompt_level": a.get("prompt_level"), **session_usage(c, hit[1])})

    total = {k: sum(s[k] for s in sessions) for k in
             ("turns", "input_new", "input_cache_read", "cache_write", "output", "reasoning")}
    total["cost_usd"] = round(sum(s["cost_usd"] for s in sessions), 6)
    row = {"ts_ms": int(time.time() * 1000), "run_id": run_id, "agent": agent,
           "sessions": len(sessions), "unmatched_forwards": unmatched, **total,
           "run_config": {k: v for k, v in cfg.items() if k not in ("ts_ms", "run_id", "scenario", "event", "host")},
           "per_session": sessions}
    return row


def main():
    run_id, append = sys.argv[1], "--append" in sys.argv
    row = usage(run_id)
    print(json.dumps(row, ensure_ascii=False, indent=1))
    if append:
        with open(RUNS / "usage.jsonl", "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
