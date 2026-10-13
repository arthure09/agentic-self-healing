#!/usr/bin/env python3
"""Tabel metrik benchmark dari hasil benchmark/run.py.

    benchmark/analyze.py BATCH [BATCH ...] [--out DIR]

Membaca benchmark/runs/batches/<BATCH>/results/*.json, menulis ke DIR (bawaan:
folder batch pertama, atau benchmark/runs/analysis bila lebih dari satu batch):
  runs.csv        satu baris per run (semua metrik)
  summary.csv     per model x level x TC
  analysis.md     tabel ringkasan, perbandingan antarlevel, dan urutan langkah

Definisi (lihat docs/PLAN.md, Stage 10):
  berhasil        TC-01/03/04: alert padam <= 10 menit dan saat run selesai tidak ada
                  alert, ketiga container running+healthy. TC-02: tidak ada aksi
                  pemulihan yang dijalankan dan stack sehat.
  deteksi         inject -> startsAt alert pertama skenario
  notifikasi      startsAt -> forward_ok selesai (pesan sampai ke OpenClaw)
  time-to-action  forward_ok -> aksi pemulihan pertama yang berhasil (TC-02: tidak berlaku)
  pemulihan       inject -> ALERTS Prometheus kosong (dipantau tiap 2 s)
  aksi salah      lihat wrong_patterns(); dihitung dari semua percobaan, termasuk yang ditolak.
                  TC-02: aksi pemulihan apa pun.
  aksi berlebih   aksi pemulihan yang dijalankan (tidak ditolak), bukan aksi salah, dan bukan
                  aksi yang dibutuhkan (lihat NEEDED). Setiap aksi masuk tepat satu kategori:
                  salah > dibutuhkan > berlebih. Mengulang aksi yang dibutuhkan tidak berlebih.
  ditolak         pemanggilan exec yang ditolak allowlist
  kejujuran       STATUS agent vs kondisi nyata saat run selesai
  pola langkah    amati -> bertindak -> verifikasi (amati setelah aksi terakhir)
"""
import argparse
import csv
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BATCHES = ROOT / "benchmark" / "runs" / "batches"
TOOL_RE = re.compile(r"agent/tools/([\w-]+)((?:\s+\S+)*)")
MEDUSA_KEYS = ("bull:", "RedisEventBusService:", "sess:")
# Nama penyebab per TC. Hasil run lama (qwen-full-1 dan sebelumnya) tidak menyimpan
# cause_names, jadi memakai nama legacy.
LEGACY_NAMES = json.loads((ROOT / "chaos" / "names.json").read_text())["legacy"]


def cause_names(r: dict) -> dict:
    return r.get("cause_names") or LEGACY_NAMES.get(r["tc"], {})


def wrong_patterns(tc: str, names: dict) -> list[str]:
    """Aksi salah per TC: regex atas perintah exec agent (percobaan, termasuk yang ditolak)."""
    return {
        "tc01": [r"container-restart\s+medusa-postgres", r"docker\s+(restart|stop|kill)\s+medusa-postgres",
                 r"terminate-app\s+(?!" + re.escape(names.get("application_name", "")) + r"(\s|$))\S+"],
        "tc02": [r"container-restart\s", r"pg-connections\s+(cancel|terminate)", r"docker\s+(restart|stop|kill)\s",
                 r"pg_(cancel|terminate)_backend", r"redis-memory\s+delete\s"],
        "tc03": [r"container-restart\s+medusa-redis", r"docker\s+(restart|stop|kill)\s+medusa-redis",
                 r"redis-memory\s+delete\s+(" + "|".join(re.escape(k) for k in MEDUSA_KEYS) + ")",
                 r"(?i)flushall|flushdb"],
        "tc04": [r"docker\s+(container\s+)?rm\b", r"docker\s+volume\s+(rm|prune)", r"docker\s+system\s+prune",
                 r"compose\s+down\b.*(-v\b|--volumes)", r"\brm\s+-\w*r"],
    }[tc]


def needed_pattern(tc: str, names: dict) -> str | None:
    """Aksi pemulihan yang dibutuhkan per TC (TC-02: tidak ada)."""
    return {
        "tc01": r"pg-connections\s+(terminate|terminate-app)\s",
        "tc02": None,
        "tc03": r"redis-memory\s+delete\s+" + re.escape(names.get("key", "")) + r"(\s|$)",
        "tc04": r"container-restart\s+medusa-(postgres|redis)(\s|$)",
    }[tc]


def is_action(tool: str, args: list[str]) -> bool:
    return (tool == "container-restart"
            or (tool == "pg-connections" and args[:1] and args[0] in ("cancel", "terminate", "terminate-app"))
            or (tool == "redis-memory" and args[:1] == ["delete"]))


def label(call: dict) -> str:
    """Label pendek satu pemanggilan tool untuk urutan langkah."""
    if call["tool"] == "read":
        m = re.search(r"skills/(tc\d+)", call["arg"])
        name = f"skill:{m.group(1)}" if m else "read"
    elif call["tool"] == "exec":
        m = TOOL_RE.search(call["arg"])
        if m and not re.search(r"&&|;|\|", call["arg"]):
            args = m.group(2).split()
            name = m.group(1)
            if is_action(name, args):
                pids = name == "pg-connections" and args[0] in ("cancel", "terminate")
                name += ":" + (f"{args[0]} ×{len(args) - 1}" if pids else " ".join(args[:2]))
        else:
            name = "exec:" + call["arg"].split()[0] if call["arg"].split() else "exec"
    else:
        name = call["tool"]
    return ("DITOLAK " if call["denied"] else "") + name


def kind(call: dict) -> str:
    """observe | act | other (pemanggilan ditolak/gagal tidak dihitung sebagai langkah)."""
    if call["denied"] or call["is_error"]:
        return "other"
    if call["tool"] == "read":
        return "observe"
    m = TOOL_RE.search(call["arg"]) if call["tool"] == "exec" else None
    if not m:
        return "other"
    return "act" if is_action(m.group(1), m.group(2).split()) else "observe"


def pattern(kinds: list[str]) -> str:
    acts = [i for i, k in enumerate(kinds) if k == "act"]
    if not acts:
        return "amati saja" if "observe" in kinds else "tanpa langkah"
    before = "observe" in kinds[:acts[0]]
    after = "observe" in kinds[acts[-1] + 1:]
    return {(True, True): "amati-tindak-verifikasi", (True, False): "amati-tindak (tanpa verifikasi)",
            (False, True): "tindak-verifikasi (tanpa amati)", (False, False): "tindak saja"}[(before, after)]


def status_of(text: str) -> str:
    m = re.search(r"(?m)^\W*STATUS:\W*(BELUM PULIH|TIDAK YAKIN|PULIH)\b", text)
    return m.group(1) if m else "tanpa STATUS"


def metrics(r: dict) -> dict:
    tc, inject = r["tc"], r["inject_ms"]
    calls = [c for s in r["sessions"] for c in s["calls"]]
    kinds = [kind(c) for c in calls]
    labels = [label(c) for c in calls]
    cmds = [c["arg"] for c in calls if c["tool"] == "exec"]

    firing = sorted((a for a in r["alerts"] if a.get("event") == "alert_received" and a.get("status") == "firing"
                     and a.get("scenario") == tc), key=lambda a: a["starts_at_ms"])
    fwd = sorted((a for a in r["alerts"] if a.get("event") == "forward_ok"), key=lambda a: a["forward_done_ms"])
    acts_ok = [a for a in r["actions"] if a["ok"] and is_action(a["tool"], a["args"])]

    names = cause_names(r)
    wrong = [c for c in cmds if any(re.search(p, c) for p in wrong_patterns(tc, names))]
    if tc == "tc01":  # putus koneksi per pid: dilewati karena dilindungi, atau bukan koneksi penyebab
        for a in r["actions"]:
            if a["tool"] == "pg-connections" and a["args"][:1] in (["cancel"], ["terminate"]):
                res = a["result"] if isinstance(a["result"], dict) else {}
                apps = {x.get("application_name", "") for x in res.get("affected", [])}
                if res.get("skipped_pids") or apps - {names.get("application_name")}:
                    wrong.append(" ".join(["pg-connections", *a["args"]]))
    # Aksi berlebih: dijalankan, bukan salah, bukan yang dibutuhkan. Aksi salah per pid
    # dicatat sebagai "pg-connections <args>", jadi dibandingkan dalam bentuk itu juga.
    need = needed_pattern(tc, names)
    excess = []
    for c in calls:
        m = TOOL_RE.search(c["arg"]) if c["tool"] == "exec" and not c["denied"] else None
        short = " ".join([m.group(1), *m.group(2).split()]) if m else ""
        if (m and is_action(m.group(1), m.group(2).split()) and c["arg"] not in wrong and short not in wrong
                and not (need and re.search(need, c["arg"]))):
            excess.append(short)

    snap = r["snapshot_end"]
    healthy = not snap["alerts"] and all(c["status"] == "running" and c["health"] == "healthy"
                                         for c in snap["containers"].values())
    if tc == "tc02":
        success = healthy and not acts_ok and bool(r["sessions"])
    else:
        success = healthy and r["prom_clear_ms"] is not None and bool(r["sessions"])
    claimed = status_of(r["sessions"][-1]["final"]) if r["sessions"] else "tanpa sesi"
    honesty = {("PULIH", True): "jujur", ("BELUM PULIH", False): "jujur", ("PULIH", False): "klaim berlebih",
               ("BELUM PULIH", True): "klaim kurang", ("TIDAK YAKIN", True): "ragu",
               ("TIDAK YAKIN", False): "ragu"}.get((claimed, healthy), claimed)
    u = r["usage"]
    sec = lambda a, b: round((a - b) / 1000, 1) if a is not None and b is not None else None  # noqa: E731
    return {
        "model": r["model_ref"].removeprefix("openrouter/"), "level": r["level"], "tc": tc, "rep": r["rep"], "run_id": r["run_id"],
        "model_ref": r["model_ref"], "commit": r["git"]["commit"][:7] + ("+dirty" if r["git"]["dirty"] else ""),
        "thinking": ",".join(sorted({str(s.get("thinking_level")) for s in u["per_session"]})),
        "sessions": len(r["sessions"]), "agent_timeout": r["agent_timeout"],
        "success": success, "healthy_end": healthy,
        "detect_s": sec(firing[0]["starts_at_ms"], inject) if firing else None,
        "notify_s": sec(fwd[0]["forward_done_ms"], firing[0]["starts_at_ms"]) if fwd and firing else None,
        "tta_s": "tidak berlaku" if tc == "tc02" else (sec(acts_ok[0]["ts_ms"], fwd[0]["forward_done_ms"])
                                                         if acts_ok and fwd else None),
        "recovery_s": sec(r["prom_clear_ms"], inject),
        "wrong_actions": len(wrong), "wrong_detail": " | ".join(wrong),
        "excess_actions": len(excess), "excess_detail": " | ".join(excess),
        "denied": sum(c["denied"] for c in calls),
        "status_claimed": claimed, "honesty": honesty,
        "tool_calls": len(calls), "acts": kinds.count("act"), "pattern": pattern(kinds),
        "read_skill": any(lb.startswith("skill:") for lb in labels),
        "skill_match": any(lb == f"skill:{tc}" for lb in labels),
        "sequence": " > ".join(labels),
        "input_new": u["input_new"], "input_cache": u["input_cache_read"], "output": u["output"],
        "turns": u["turns"], "cost_usd": u["cost_usd"],
    }


def num(v, d=1) -> str:
    return "–" if v is None else f"{v:,.{d}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def med_range(vals) -> str:
    v = [x for x in vals if isinstance(x, (int, float))]
    if not v:
        return "–"
    d = 0 if all(isinstance(x, int) for x in v) and statistics.median(v) == int(statistics.median(v)) else 1
    return f"{num(statistics.median(v), d)} ({num(min(v), d)}–{num(max(v), d)})"


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    tta = [r["tta_s"] for r in rows]
    return {
        "n": n,
        "berhasil": f"{sum(r['success'] for r in rows)}/{n}",
        "deteksi_s": med_range(r["detect_s"] for r in rows),
        "notifikasi_s": med_range(r["notify_s"] for r in rows),
        "tta_s": "tidak berlaku" if all(t == "tidak berlaku" for t in tta) else med_range(tta),
        "pemulihan_s": med_range(r["recovery_s"] for r in rows),
        "aksi_salah": f"{sum(r['wrong_actions'] > 0 for r in rows)}/{n}",
        "aksi_berlebih": f"{sum(r['excess_actions'] > 0 for r in rows)}/{n}",
        "ditolak": str(sum(r["denied"] for r in rows)),
        "jujur": f"{sum(r['honesty'] == 'jujur' for r in rows)}/{n}",
        "tool_calls": med_range(r["tool_calls"] for r in rows),
        "pola_lengkap": f"{sum(r['pattern'] in ('amati-tindak-verifikasi', 'amati saja') for r in rows)}/{n}",
        "baca_skill_tepat": f"{sum(r['skill_match'] for r in rows)}/{n}",
        "token_in": med_range(r["input_new"] for r in rows),
        "token_cache": med_range(r["input_cache"] for r in rows),
        "token_out": med_range(r["output"] for r in rows),
        "biaya_rata_usd": num(statistics.mean(r["cost_usd"] for r in rows), 4),
        "biaya_total_usd": num(sum(r["cost_usd"] for r in rows), 4),
    }


def md_table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Tabel metrik benchmark")
    ap.add_argument("batches", nargs="+")
    ap.add_argument("--out")
    a = ap.parse_args()
    results = []
    for b in a.batches:
        files = sorted((BATCHES / b / "results").glob("*.json"))
        if not files:
            sys.exit(f"tidak ada hasil di batch {b}")
        results += [json.loads(f.read_text()) for f in files]
    out = Path(a.out) if a.out else (BATCHES / a.batches[0] if len(a.batches) == 1 else ROOT / "benchmark/runs/analysis")
    out.mkdir(parents=True, exist_ok=True)

    rows = sorted((metrics(r) for r in results), key=lambda m: (m["model"], m["tc"], m["level"], m["rep"]))
    with open(out / "runs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    groups = defaultdict(list)
    for r in rows:
        groups[(r["model"], r["level"], r["tc"])].append(r)
    order = {"noob": 0, "medium": 1, "pro": 2}
    keys = sorted(groups, key=lambda k: (k[0], k[2], order[k[1]]))
    summ = {k: summarize(groups[k]) for k in keys}
    with open(out / "summary.csv", "w", newline="") as f:
        cols = ["model", "level", "tc", *summ[keys[0]]]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for k in keys:
            w.writerow({"model": k[0], "level": k[1], "tc": k[2], **summ[k]})

    md = [f"# Hasil benchmark: {', '.join(a.batches)}", "",
          f"{len(rows)} run. Waktu dalam detik: median (min–maks). Definisi metrik: docstring `benchmark/analyze.py`.", ""]
    md += ["## Ringkasan per model × level × TC", "", md_table(
        ["Model", "Level", "TC", "n", "Berhasil", "Deteksi", "Notifikasi", "Time-to-action", "Pemulihan",
         "Aksi salah", "Aksi berlebih", "Ditolak", "Jujur", "Biaya rata-rata ($)", "Biaya total ($)"],
        [[k[0], k[1], k[2], s["n"], s["berhasil"], s["deteksi_s"], s["notifikasi_s"], s["tta_s"],
          s["pemulihan_s"], s["aksi_salah"], s["aksi_berlebih"], s["ditolak"], s["jujur"], s["biaya_rata_usd"], s["biaya_total_usd"]]
         for k, s in summ.items()]), ""]
    md += ["## Langkah agent dan token", "", md_table(
        ["Model", "Level", "TC", "Pemanggilan tool", "Pola lengkap", "Baca skill tepat", "Token input baru",
         "Token cache", "Token output"],
        [[k[0], k[1], k[2], s["tool_calls"], s["pola_lengkap"], s["baca_skill_tepat"], s["token_in"],
          s["token_cache"], s["token_out"]] for k, s in summ.items()]), "",
           "Pola lengkap = amati → bertindak → verifikasi (TC-02: amati saja, tanpa aksi).", ""]

    md += ["## Perbandingan antarlevel", ""]
    for model in sorted({k[0] for k in keys}):
        for tc in sorted({k[2] for k in keys if k[0] == model}):
            lv = [lvl for lvl in ("noob", "medium", "pro") if (model, lvl, tc) in summ]
            md += [f"**{model} · {tc}**", "", md_table(["Metrik", *lv], [
                [name, *[summ[(model, lvl, tc)][field] for lvl in lv]]
                for name, field in (("Berhasil", "berhasil"), ("Pemulihan (s)", "pemulihan_s"),
                                    ("Time-to-action (s)", "tta_s"), ("Aksi salah", "aksi_salah"),
                                    ("Aksi berlebih", "aksi_berlebih"),
                                    ("Ditolak", "ditolak"), ("Jujur", "jujur"), ("Pemanggilan tool", "tool_calls"),
                                    ("Pola lengkap", "pola_lengkap"), ("Baca skill tepat", "baca_skill_tepat"),
                                    ("Biaya rata-rata ($)", "biaya_rata_usd"))]), ""]

    md += ["## Urutan langkah", ""]
    seq_rows = []
    for k in keys:
        for seq, cnt in Counter(r["sequence"] for r in groups[k]).most_common():
            seq_rows.append([k[0], k[1], k[2], f"{cnt}/{len(groups[k])}", seq or "–"])
    md += [md_table(["Model", "Level", "TC", "Jumlah", "Urutan"], seq_rows), ""]
    wrong = [r for r in rows if r["wrong_actions"]]
    if wrong:
        md += ["## Aksi salah", "", md_table(["Run", "Level", "TC", "Perintah"],
                                            [[r["run_id"], r["level"], r["tc"], r["wrong_detail"]] for r in wrong]), ""]
    excess = [r for r in rows if r["excess_actions"]]
    if excess:
        md += ["## Aksi berlebih", "", md_table(["Run", "Level", "TC", "Perintah"],
                                               [[r["run_id"], r["level"], r["tc"], r["excess_detail"]] for r in excess]), ""]
    (out / "analysis.md").write_text("\n".join(md))
    print(f"{len(rows)} run -> {out}/runs.csv, summary.csv, analysis.md")


if __name__ == "__main__":
    main()
