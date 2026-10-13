"""Utilitas bersama chaos scripts: baca .env, catat event JSONL, kelola pidfile.

Setiap event ditulis sebagai satu baris JSON ke benchmark/runs/events.jsonl
dengan timestamp epoch milidetik (`ts_ms`), supaya bisa dipasangkan dengan
timestamp alert (alert-bridge) dan aksi agent untuk menghitung metrik evaluasi.
"""
import json
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "benchmark" / "runs"
EVENTS_FILE = RUNS_DIR / "events.jsonl"
PID_DIR = RUNS_DIR / "pids"
# Nama penyebab yang terlihat agent (application_name, key, skema): satu sumber.
NAMES = json.loads((ROOT / "chaos" / "names.json").read_text())["current"]


def load_env(path: Path = ROOT / ".env") -> dict:
    """Baca .env (KEY=VALUE) tanpa dependensi tambahan. Variabel lingkungan menang."""
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k in env})
    return env


def pg_dsn(env: dict, application_name: str) -> str:
    host = os.environ.get("PG_HOST", "127.0.0.1")
    port = os.environ.get("PG_PORT", "5432")
    return (
        f"host={host} port={port} dbname={env['POSTGRES_DB']} "
        f"user={env['POSTGRES_USER']} password={env['POSTGRES_PASSWORD']} "
        f"application_name={application_name} connect_timeout=5"
    )


def redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def new_run_id(scenario: str) -> str:
    # RUN_ID dari luar memungkinkan harness benchmark mengaitkan satu run
    # dengan alert dan aksi agent.
    return os.environ.get("RUN_ID") or (
        f"{scenario}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')[:-4]}"
    )


def log_event(run_id: str, scenario: str, event: str, **data) -> dict:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "ts_ms": now_ms(),
        "run_id": run_id,
        "scenario": scenario,
        "event": event,
        "host": socket.gethostname(),
        **data,
    }
    with EVENTS_FILE.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(record, ensure_ascii=False), flush=True)
    return record


def write_pidfile(scenario: str) -> Path:
    PID_DIR.mkdir(parents=True, exist_ok=True)
    path = PID_DIR / f"{scenario}.pid"
    path.write_text(str(os.getpid()))
    return path
