#!/usr/bin/env python3
"""Web panel benchmark: atur dan jalankan batch (benchmark/run.py), lihat hasil (benchmark/analyze.py).

    python3 benchmark/web.py          # http://127.0.0.1:8090 (BENCH_WEB_HOST/PORT di .env)

Login: Basic auth, user "admin", password BENCH_WEB_PASSWORD di .env.
Hanya satu batch berjalan pada satu waktu. Batch dijalankan sebagai proses terpisah
(log di benchmark/runs/batches/<batch>/run.log), jadi tetap jalan walau web di-restart.
Hanya pustaka standar Python.
"""
import base64
import hmac
import html
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BATCHES = ROOT / "benchmark" / "runs" / "batches"
ACTIVE = BATCHES / ".active.json"
ENV = dict(line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines()
           if "=" in line and not line.lstrip().startswith("#"))
HOST, PORT = ENV.get("BENCH_WEB_HOST", "127.0.0.1"), int(ENV.get("BENCH_WEB_PORT", "8090"))
PASSWORD = ENV.get("BENCH_WEB_PASSWORD", "")
LEVELS, TCS, MODELS = ("noob", "medium", "pro"), ("tc01", "tc02", "tc03", "tc04"), ("qwen", "gemini")
NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")
CSV_FILES = ("runs.csv", "summary.csv", "analysis.md")

CSS = """
:root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#6b6b66;--card:#fff;--line:#deded8;--accent:#2f5d8a;--ok:#2e7d4f;--bad:#b23b3b}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ececea;--muted:#a3a39d;--card:#1f1f1d;--line:#363633;--accent:#7fb0e0;--ok:#6cc08f;--bad:#e58585}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
header{display:flex;gap:20px;align-items:center;padding:12px 16px;border-bottom:1px solid var(--line);background:var(--card)}
header b{margin-right:auto}header a{color:var(--accent);text-decoration:none}main{max-width:1200px;margin:0 auto;padding:16px}
section{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px;margin-bottom:16px}
h1{font-size:20px}h2{font-size:17px;margin-top:0}h3{font-size:15px}label{display:inline-flex;gap:6px;align-items:center;margin-right:14px}
input,select,button{font:inherit;color:inherit;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:6px 10px}
button{background:var(--accent);color:#fff;border:0;cursor:pointer}button.stop{background:var(--bad)}button:disabled{opacity:.5;cursor:default}
.row{margin:10px 0}.muted{color:var(--muted)}.ok{color:var(--ok)}.bad{color:var(--bad)}
.scroll{overflow-x:auto}table{border-collapse:collapse;margin:8px 0;font-size:13px}th,td{border:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}
th{background:var(--bg)}pre{background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:10px;overflow:auto;max-height:420px;font-size:12px}
.bar{height:8px;background:var(--line);border-radius:4px;overflow:hidden;max-width:420px}.bar div{height:100%;background:var(--accent)}
"""


def active() -> dict | None:
    """Batch yang sedang berjalan, atau None (berkas .active.json dibersihkan bila prosesnya sudah mati)."""
    try:
        a = json.loads(ACTIVE.read_text())
        os.kill(a["pid"], 0)
        if "benchmark/run.py" in Path(f"/proc/{a['pid']}/cmdline").read_text(errors="ignore"):
            return a
    except (OSError, ValueError, KeyError):
        pass
    ACTIVE.unlink(missing_ok=True)
    return None


def batches() -> list[dict]:
    out = []
    for d in sorted(BATCHES.glob("*/plan.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        plan = json.loads(d.read_text())
        done = sum((d.parent / "results" / f"{r['key']}.json").exists() for r in plan["runs"])
        out.append({"name": d.parent.name, "model": plan["model"], "seed": plan["seed"], "total": len(plan["runs"]),
                    "done": done, "levels": sorted({r["level"] for r in plan["runs"]}, key=LEVELS.index),
                    "tcs": sorted({r["tc"] for r in plan["runs"]}),
                    "reps": max(r["rep"] for r in plan["runs"]), "created": time.strftime(
                        "%Y-%m-%d %H:%M", time.localtime(plan["created_ms"] / 1000))})
    return out


def start(form: dict) -> str:
    if active():
        return "Masih ada batch yang berjalan."
    name = form.get("batch", [""])[0].strip()
    model = form.get("model", [""])[0]
    levels = [lv for lv in LEVELS if lv in form.get("level", [])]
    tcs = [tc for tc in TCS if tc in form.get("tc", [])]
    reps, seed = form.get("reps", ["1"])[0], form.get("seed", [""])[0].strip()
    if not NAME_RE.fullmatch(name) or model not in MODELS or not levels or not tcs:
        return "Isian tidak valid: nama batch (huruf/angka/-/_), model, minimal satu level dan satu TC."
    if not reps.isdigit() or not 1 <= int(reps) <= 10 or (seed and not seed.isdigit()):
        return "Pengulangan harus 1–10 dan seed berupa angka."
    plan = BATCHES / name / "plan.json"
    if plan.exists() and json.loads(plan.read_text())["model"] != model:
        return f"Batch {name} sudah ada dengan model lain."
    cmd = [sys.executable, "benchmark/run.py", "--batch", name, "--model", model,
           "--levels", ",".join(levels), "--tcs", ",".join(tcs), "--reps", reps] + (["--seed", seed] if seed else [])
    (BATCHES / name).mkdir(parents=True, exist_ok=True)
    logf = open(BATCHES / name / "run.log", "a")
    logf.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} mulai dari web: {' '.join(cmd[1:])}\n")
    logf.flush()
    p = subprocess.Popen(cmd, cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)
    ACTIVE.write_text(json.dumps({"pid": p.pid, "batch": name, "cmd": cmd[1:], "started_ms": int(time.time() * 1000)}))
    return f"Batch {name} dimulai."


def stop() -> str:
    a = active()
    if not a:
        return "Tidak ada batch yang berjalan."
    os.kill(a["pid"], signal.SIGTERM)  # run.py mengembalikan level dan me-reset stack sebelum keluar
    return f"Batch {a['batch']} dihentikan; reset penutup berjalan (±1 menit)."


def log_tail(name: str, n: int = 40) -> str:
    f = BATCHES / name / "run.log"
    return "\n".join(f.read_text(errors="replace").splitlines()[-n:]) if f.exists() else ""


def md_to_html(md: str) -> str:
    """Cukup untuk keluaran analyze.py: judul, tabel, paragraf, **tebal**, `kode`."""
    out, table = [], []

    def inline(s: str) -> str:
        s = html.escape(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        return re.sub(r"`(.+?)`", r"<code>\1</code>", s)

    def flush():
        if table:
            rows = [[c.strip() for c in r.strip().strip("|").split("|")] for r in table if not re.fullmatch(r"\|[-|]+\|?", r.strip())]
            out.append('<div class="scroll"><table><tr>' + "".join(f"<th>{inline(c)}</th>" for c in rows[0]) + "</tr>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
                       + "</table></div>")
            table.clear()
    for line in md.splitlines():
        if line.startswith("|"):
            table.append(line)
            continue
        flush()
        m = re.match(r"(#{1,3}) (.*)", line)
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    flush()
    return "\n".join(out)


def page(title: str, body: str, refresh: bool = False) -> bytes:
    meta = '<meta http-equiv="refresh" content="15">' if refresh else ""
    return f"""<!doctype html><html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">{meta}<title>{html.escape(title)}</title>
<style>{CSS}</style></head><body><header><b>Benchmark Agentic</b><a href="/">Jalankan</a><a href="/hasil">Hasil</a></header>
<main>{body}</main></body></html>""".encode()


def run_page(msg: str = "") -> bytes:
    a = active()
    bs = batches()
    note = f'<section><b>{html.escape(msg)}</b></section>' if msg else ""
    if a:
        b = next((x for x in bs if x["name"] == a["batch"]), None)
        pct = 100 * b["done"] / b["total"] if b and b["total"] else 0
        status = f"""<section><h2>Sedang berjalan: {html.escape(a['batch'])}</h2>
<p class="muted">{html.escape(' '.join(a['cmd']))} · mulai {time.strftime('%H:%M', time.localtime(a['started_ms'] / 1000))}</p>
<p>{b['done'] if b else 0}/{b['total'] if b else '?'} run selesai</p><div class="bar"><div style="width:{pct:.0f}%"></div></div>
<form method="post" action="/stop" onsubmit="return confirm('Hentikan batch? Run yang sedang berjalan dibatalkan, lalu stack di-reset.')">
<p><button class="stop">Hentikan</button></p></form><h3>Log</h3><pre>{html.escape(log_tail(a['batch']))}</pre>
<p class="muted">Halaman diperbarui otomatis tiap 15 detik.</p></section>"""
    else:
        status = '<section><h2>Status</h2><p class="ok">Tidak ada batch yang berjalan.</p></section>'
    chk = lambda name, vals, on: "".join(  # noqa: E731
        f'<label><input type="checkbox" name="{name}" value="{v}"{" checked" if v in on else ""}>{v}</label>' for v in vals)
    form = f"""<section><h2>Jalankan batch</h2>
<form method="post" action="/start" onsubmit="const n=this.querySelectorAll('[name=level]:checked').length*this.querySelectorAll('[name=tc]:checked').length*this.reps.value;return confirm('Jalankan '+n+' run (±3,5 menit per run, ±'+Math.round(n*3.5/60*10)/10+' jam)?')">
<div class="row"><label>Nama batch <input name="batch" required pattern="[A-Za-z0-9_-]{{1,40}}" placeholder="qwen-uji"></label>
<label>Model <select name="model">{''.join(f'<option>{m}</option>' for m in MODELS)}</select></label></div>
<div class="row">Level: {chk('level', LEVELS, LEVELS)}</div>
<div class="row">TC: {chk('tc', TCS, TCS)}</div>
<div class="row"><label>Pengulangan <input name="reps" type="number" min="1" max="10" value="1" style="width:5em"></label>
<label>Seed (opsional) <input name="seed" inputmode="numeric" pattern="[0-9]*" style="width:9em"></label></div>
<p class="muted">Nama batch yang sudah ada = melanjutkan batch itu (urutan dan seed lama dipakai; level/TC/pengulangan baru diabaikan).</p>
<button{' disabled' if a else ''}>Mulai</button></form></section>"""
    rows = "".join(f"""<tr><td>{html.escape(b['name'])}</td><td>{b['model']}</td><td>{', '.join(b['levels'])}</td>
<td>{', '.join(b['tcs'])}</td><td>{b['reps']}</td><td>{b['seed']}</td><td>{b['done']}/{b['total']}</td><td>{b['created']}</td>
<td><a href="/hasil?batch={urllib.parse.quote(b['name'])}">hasil</a></td></tr>""" for b in bs)
    table = (f"""<section><h2>Batch</h2><div class="scroll"><table><tr><th>Nama</th><th>Model</th><th>Level</th><th>TC</th>
<th>Ulang</th><th>Seed</th><th>Selesai</th><th>Dibuat</th><th></th></tr>{rows}</table></div></section>""" if bs else "")
    return page("Jalankan · Benchmark", note + status + form + table, refresh=bool(a))


def result_page(names: list[str]) -> bytes:
    bs = batches()
    pick = "".join(f'<label><input type="checkbox" name="batch" value="{html.escape(b["name"])}"'
                   f'{" checked" if b["name"] in names else ""}>{html.escape(b["name"])} ({b["model"]}, {b["done"]}/{b["total"]})</label>'
                   for b in bs if b["done"])
    body = f"""<section><h2>Pilih batch</h2><form method="get" action="/hasil"><div class="row">{pick or '<span class="muted">Belum ada hasil.</span>'}</div>
<button>Tampilkan</button> <span class="muted">Pilih beberapa batch untuk membandingkan model.</span></form></section>"""
    names = [n for n in names if NAME_RE.fullmatch(n) and (BATCHES / n / "plan.json").exists()]
    if names:
        out = BATCHES / names[0] if len(names) == 1 else ROOT / "benchmark/runs/analysis"
        p = subprocess.run([sys.executable, "benchmark/analyze.py", *names, "--out", str(out)],
                           cwd=ROOT, capture_output=True, text=True)
        if p.returncode:
            body += f'<section><p class="bad">analyze.py gagal</p><pre>{html.escape(p.stderr or p.stdout)}</pre></section>'
        else:
            q = urllib.parse.urlencode([("batch", n) for n in names])
            links = " · ".join(f'<a href="/file?{q}&name={f}">{f}</a>' for f in CSV_FILES)
            body += f'<section><p>Unduh: {links}</p>{md_to_html((out / "analysis.md").read_text())}</section>'
    return page("Hasil · Benchmark", body)


class Handler(BaseHTTPRequestHandler):
    def _authed(self) -> bool:
        h = self.headers.get("Authorization", "")
        if PASSWORD and h.startswith("Basic "):
            try:
                user, _, pw = base64.b64decode(h[6:]).decode().partition(":")
            except ValueError:
                return False
            return user == "admin" and hmac.compare_digest(pw, PASSWORD)
        return False

    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8", extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _guard(self) -> bool:
        if self._authed():
            return True
        self._send(401, b"Login diperlukan", "text/plain; charset=utf-8", {"WWW-Authenticate": 'Basic realm="benchmark"'})
        return False

    def do_GET(self):
        if not self._guard():
            return
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        if url.path == "/":
            self._send(200, run_page(q.get("msg", [""])[0]))
        elif url.path == "/hasil":
            self._send(200, result_page(q.get("batch", [])))
        elif url.path == "/file":
            names, f = q.get("batch", []), q.get("name", [""])[0]
            if f not in CSV_FILES or not names or not all(NAME_RE.fullmatch(n) for n in names):
                return self._send(404, b"tidak ada")
            path = (BATCHES / names[0] if len(names) == 1 else ROOT / "benchmark/runs/analysis") / f
            if not path.exists():
                return self._send(404, b"tidak ada")
            self._send(200, path.read_bytes(), "text/csv; charset=utf-8" if f.endswith(".csv") else "text/markdown; charset=utf-8",
                       {"Content-Disposition": f'attachment; filename="{"-".join(names)}-{f}"'})
        else:
            self._send(404, b"tidak ada")

    def do_POST(self):
        if not self._guard():
            return
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlparse(origin).netloc != self.headers.get("Host"):
            return self._send(403, b"asal permintaan ditolak")
        form = urllib.parse.parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
        msg = start(form) if self.path == "/start" else stop() if self.path == "/stop" else None
        if msg is None:
            return self._send(404, b"tidak ada")
        # redirect supaya refresh browser tidak mengirim ulang perintah
        self._send(303, b"", extra={"Location": "/?" + urllib.parse.urlencode({"msg": msg})})

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    if not PASSWORD:
        sys.exit("BENCH_WEB_PASSWORD belum diisi di .env")
    BATCHES.mkdir(parents=True, exist_ok=True)
    print(f"benchmark web: http://{HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
