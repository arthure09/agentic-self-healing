"""Bagian bersama tool agent: panggil docker, batasi ke stack `agentic`, audit log.

Setiap tool memanggil `run(nama, fungsi)`. Hasil fungsi dicetak sebagai JSON
dan dicatat ke benchmark/runs/actions.jsonl. ValueError = permintaan ditolak
(guardrail), dicatat dengan ok=false.
"""
import json
import os
import re
import subprocess
import sys
import time

PROJECT = "agentic"
DOCKER = "/usr/bin/docker"
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
AUDIT_LOG = os.path.join(REPO, "benchmark", "runs", "actions.jsonl")
NAME_RE = r"[a-z0-9][a-z0-9_.-]{0,62}"


def docker(*args: str, input: str | None = None, timeout: int = 20) -> str:
    return subprocess.run([DOCKER, *args], capture_output=True, text=True, check=True,
                          timeout=timeout, input=input).stdout


def project_containers() -> list[str]:
    return docker("ps", "-a", "--filter", f"label=com.docker.compose.project={PROJECT}",
                  "--format", "{{.Names}}").split()


def check_names(names: list[str], allowed: list[str] | None = None) -> None:
    if any(not re.fullmatch(NAME_RE, n) for n in names):
        raise ValueError("argumen hanya boleh nama container")
    allowed = project_containers() if allowed is None else allowed
    bad = [n for n in names if n not in allowed]
    if bad:
        raise ValueError(f"container tidak diizinkan: {', '.join(bad)} (boleh: {', '.join(allowed)})")


def audit(tool: str, args: list[str], ok: bool, result, t0: float) -> None:
    entry = {"ts_ms": time.time_ns() // 1_000_000, "tool": tool, "args": args,
             "ok": ok, "result": result, "duration_ms": round((time.monotonic() - t0) * 1000)}
    try:
        with open(AUDIT_LOG, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"peringatan: audit log gagal ditulis: {e}", file=sys.stderr)


def run(tool: str, fn) -> int:
    t0, args = time.monotonic(), sys.argv[1:]
    try:
        result = fn(args)
    except (ValueError, subprocess.SubprocessError) as e:
        msg = (getattr(e, "stderr", None) or str(e)).strip()
        audit(tool, args, False, msg, t0)
        print(json.dumps({"error": msg}, ensure_ascii=False))
        return 1
    audit(tool, args, True, result, t0)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
