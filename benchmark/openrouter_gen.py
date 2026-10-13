#!/usr/bin/env python3
"""Unduh data generation OpenRouter untuk setiap panggilan model di satu batch.

    benchmark/openrouter_gen.py BATCH

Membaca gen-ID dari results/*.json (usage.per_session[].response_ids), memanggil
GET /api/v1/generation?id=<ID>, dan menulis satu baris JSON per ID ke
benchmark/runs/batches/<BATCH>/generation.jsonl (kolom run_id, turn, gen_id,
response). ID yang sudah tersimpan dilewati, jadi aman dijalankan ulang.
benchmark/run.py memanggilnya otomatis di akhir batch. Dipakai analyze.py untuk
TTFT (`latency`), lama panggilan (`generation_time`), token/detik, dan penyedia;
arti kolom divalidasi di docs/validasi-latency-openrouter.md.
"""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BATCHES = ROOT / "benchmark" / "runs" / "batches"
API = "https://openrouter.ai/api/v1/generation?id="


def api_key() -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise RuntimeError("OPENROUTER_API_KEY tidak ada di .env")


def get(key: str, gid: str) -> dict:
    """Satu percobaan + maks. 3 ulang untuk 429/5xx/jaringan; 404 = data belum tersedia, ikut diulang."""
    for attempt in range(4):
        try:
            req = urllib.request.Request(API + gid, headers={"Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if attempt == 3 or (e.code < 500 and e.code not in (404, 429)):
                raise
        except OSError:
            if attempt == 3:
                raise
        time.sleep(5 * (attempt + 1))
    raise AssertionError("tidak tercapai")


def fetch(batch: str) -> tuple[int, int, list[str]]:
    """(baru diunduh, total ID, ID gagal)."""
    out = BATCHES / batch / "generation.jsonl"
    done = set()
    if out.exists():
        done = {json.loads(line)["gen_id"] for line in out.read_text().splitlines()}
    todo = []
    for f in sorted((BATCHES / batch / "results").glob("*.json")):
        r = json.loads(f.read_text())
        for s in r["usage"]["per_session"]:
            for turn, gid in enumerate(s.get("response_ids") or [], 1):
                if gid and gid.startswith("gen-") and gid not in done:
                    todo.append({"run_id": r["run_id"], "key": r["key"], "session_id": s["session_id"],
                                 "turn": turn, "gen_id": gid})
    total = len(done) + len(todo)
    if not todo:
        return 0, total, []
    key, failed, n = api_key(), [], 0
    with out.open("a") as fo:
        for it in todo:
            try:
                fo.write(json.dumps({**it, "response": get(key, it["gen_id"])}, ensure_ascii=False) + "\n")
                n += 1
            except (urllib.error.URLError, OSError) as e:
                failed.append(f"{it['gen_id']}: {e}")
            time.sleep(0.2)
    return n, total, failed


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    new, total, failed = fetch(sys.argv[1])
    print(f"{sys.argv[1]}: {new} baru, {total - len(failed)}/{total} tersimpan")
    for f in failed:
        print("GAGAL", f)
    sys.exit(1 if failed else 0)
