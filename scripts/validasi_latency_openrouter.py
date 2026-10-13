#!/usr/bin/env python3
"""Validasi arti kolom `latency` dan `generation_time` di /api/v1/generation OpenRouter.

    python3 scripts/validasi_latency_openrouter.py [--model M] [--provider SLUG] [--n 10] [--wait 60]

Di luar jalur OpenClaw: mengirim N permintaan streaming (reasoning effort low,
temperature tidak dikirim, sama dengan batch; bawaan qwen/qwen3.7-plus; --provider
mengunci penyedia seperti konfigurasi Gemini) dengan prompt yang sama, mencatat waktu
kirim, chunk pertama berisi token (reasoning atau teks), chunk pertama berisi teks
jawaban, waktu selesai, serta jumlah chunk/karakter reasoning yang di-stream. Setelah
--wait detik, mengambil /api/v1/generation untuk setiap gen-ID. Hasil mentah:
benchmark/openrouter/validasi-latency-<waktu>.jsonl. Hanya pustaka standar.
"""
import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://openrouter.ai/api/v1"
PROMPT = "Jelaskan dalam tiga kalimat apa itu connection pool pada PostgreSQL."


def api_key() -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit("OPENROUTER_API_KEY tidak ada di .env")


def one_request(key: str, model: str, provider: str | None, effort: str = "low") -> dict:
    payload = {"model": model, "stream": True, "reasoning": {"effort": effort},
               "messages": [{"role": "user", "content": PROMPT}]}
    if provider:
        payload["provider"] = {"order": [provider], "allow_fallbacks": False}
    body = json.dumps(payload).encode()
    req = urllib.request.Request(f"{API}/chat/completions", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    rec = {"sent_wall_ms": time.time() * 1000}
    t0 = time.monotonic()
    first_token = first_text = None
    gen_id, usage, text_len, reason_chunks, reason_chars = None, None, 0, 0, 0
    with urllib.request.urlopen(req, timeout=120) as resp:
        rec["headers_s"] = time.monotonic() - t0
        for raw in resp:  # SSE: satu baris "data: {...}" per chunk; baris ": ..." = komentar keep-alive
            line = raw.decode().strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            chunk = json.loads(line[6:])
            gen_id = gen_id or chunk.get("id")
            usage = chunk.get("usage") or usage
            for ch in chunk.get("choices") or []:
                d = ch.get("delta") or {}
                has_reason = bool(d.get("reasoning") or d.get("reasoning_details"))
                has_text = bool(d.get("content"))
                now = time.monotonic() - t0
                if (has_reason or has_text) and first_token is None:
                    first_token = now
                if has_text and first_text is None:
                    first_text = now
                text_len += len(d.get("content") or "")
                if has_reason:
                    reason_chunks += 1
                    reason_chars += len(d.get("reasoning") or "")
    rec.update(done_s=time.monotonic() - t0, first_token_s=first_token, first_text_s=first_text,
               gen_id=gen_id, usage=usage, text_chars=text_len,
               reasoning_chunks=reason_chunks, reasoning_chars=reason_chars)
    return rec


def generation(key: str, gid: str) -> dict:
    for attempt in range(4):
        try:
            req = urllib.request.Request(f"{API}/generation?id={gid}", headers={"Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)["data"]
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500 and e.code != 404:  # 404: data belum tersedia
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"generation {gid} tidak tersedia")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--wait", type=int, default=60)
    ap.add_argument("--model", default="qwen/qwen3.7-plus")
    ap.add_argument("--effort", default="low", help="reasoning effort (batch: low)")
    ap.add_argument("--provider", help="slug penyedia OpenRouter, mis. google-ai-studio (tanpa fallback)")
    a = ap.parse_args()
    key = api_key()
    tag = a.model.split("/")[-1] + ("" if a.effort == "low" else f"-{a.effort}")
    out = ROOT / "benchmark/openrouter" / f"validasi-latency-{tag}-{time.strftime('%Y%m%dT%H%M%S')}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    recs = []
    for i in range(1, a.n + 1):
        r = one_request(key, a.model, a.provider, a.effort)
        r["i"] = i
        recs.append(r)
        print(f"{i}: {r['gen_id']} chunk token pertama {r['first_token_s']:.3f} s, selesai {r['done_s']:.3f} s", flush=True)
        time.sleep(1)
    print(f"menunggu {a.wait} s sebelum mengambil data generation...", flush=True)
    time.sleep(a.wait)
    with out.open("w") as f:
        for r in recs:
            r["generation"] = generation(key, r["gen_id"])
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            time.sleep(0.2)
    print(f"tersimpan: {out}")


if __name__ == "__main__":
    main()
