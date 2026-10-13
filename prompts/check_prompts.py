#!/usr/bin/env python3
"""Periksa template prompt sesuai definisi level di docs/PROMPT-LEVELS.md.

Jalankan: python3 prompts/check_prompts.py   (exit 1 bila ada yang gagal)
Nama alert, container, dan skill dibaca dari repo, bukan ditulis ulang di sini.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
P = ROOT / "prompts"
# Data alert yang tersedia di alert-bridge (build_message di alert-bridge/app.py).
BRIDGE_FIELDS = {"alertname", "severity", "starts_at", "summary", "description"}
# Istilah teknis yang tidak boleh muncul di teks noob (keputusan dosen 2026-10-12).
NOOB_BANNED = {"database", "server", "redis", "postgres", "koneksi", "memori", "container", "alert", "cache", "query"}

ALERTS = set(re.findall(r"alert\s*:\s*(\w+)", (ROOT / "observability/prometheus/rules/alerts.yml").read_text()))
CONTAINERS = set(re.findall(r"container_name:\s*(\S+)", (ROOT / "docker-compose.yml").read_text()))
SKILLS = {d.name for d in (ROOT / "skills").iterdir() if (d / "SKILL.md").exists()}
# Nama penyebab gangguan (lama dan baru) tidak boleh terlihat agent: agent harus menemukannya lewat tool.
_names = json.loads((ROOT / "chaos/names.json").read_text())
CAUSE_NAMES = {"chaos"} | {v for g in ("current", "legacy") for tc in _names[g].values() for v in tc.values()}
WORKSPACE = Path.home() / ".openclaw/workspace-merapi"
AGENT_VISIBLE = sorted([*P.glob("*/tc0*.txt"), *P.glob("system/*.md"), *(ROOT / "skills").glob("*/SKILL.md"),
                        *WORKSPACE.glob("*.md"), *WORKSPACE.glob("skills/*/SKILL.md")])

failures = []


def check(ok: bool, msg: str) -> None:
    if not ok:
        failures.append(msg)


def found(text: str, words) -> list[str]:
    return sorted(w for w in words if w.lower() in text.lower())


prompts = {f: f.read_text() for f in sorted([*P.glob("*/tc0*.txt"), *P.glob("system/*.md")])}
for f, text in prompts.items():
    name = f.relative_to(P)
    level = f.parent.name
    if level == "noob":
        check("{" not in text, f"2. {name}: memuat placeholder")
        for kind, words in (("alert", ALERTS), ("container", CONTAINERS), ("skill", SKILLS), ("istilah teknis", NOOB_BANNED)):
            check(not found(text, words), f"2. {name}: memuat nama {kind} {found(text, words)}")
    if level == "medium":
        bad = found(text, SKILLS | {"pg_", "redis-cli", "docker", "FLUSH"})
        check(not bad, f"3. {name}: memuat skill/perintah {bad}")
    if level in ("medium", "pro"):
        extra = set(re.findall(r"\{(\w+)\}", text)) - BRIDGE_FIELDS
        check(not extra, f"4. {name}: placeholder tidak diisi alert-bridge {sorted(extra)}")
    if level == "pro":
        tc = f.stem  # tc01..tc04
        want = [s for s in SKILLS if s.startswith(tc + "-")]
        check(len(want) == 1 and want[0] in text, f"5. {name}: tidak menyebut skill {want or tc + '-*'}")

for f in AGENT_VISIBLE:
    bad = found(f.read_text(), CAUSE_NAMES)
    check(not bad, f"1. {f}: memuat nama penyebab gangguan {bad}")

report = (P / "system/_report-format.md").read_text().strip()
check(report in (P / "system/pro.md").read_text(), "6. system/pro.md: bagian laporan akhir beda dengan _report-format.md")

print(f"{len(prompts)} prompt + {len(AGENT_VISIBLE)} file terlihat agent diperiksa; alert={sorted(ALERTS)}; skill={sorted(SKILLS)}")
print("\n".join(failures) if failures else "SEMUA LOLOS (cek 1-6)")
sys.exit(1 if failures else 0)
