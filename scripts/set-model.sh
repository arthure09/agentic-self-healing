#!/usr/bin/env bash
# Ganti model agent merapi: set-model.sh qwen|gemini
# Hanya agents.entries.merapi.model yang berubah (tanpa fallback, supaya run tidak
# diam-diam pindah model). Skill, tool, AGENTS.md, guardrail, allowlist, dan template
# prompt tidak disentuh. Thinking dan temperature tidak di-set (bawaan provider);
# level thinking yang benar-benar dipakai dicatat per sesi oleh benchmark/run_usage.py.
# Gateway membaca ulang perubahan agents.* tanpa restart.
set -euo pipefail

case "${1:-}" in
  qwen)   MODEL="openrouter/qwen/qwen3.7-plus" ;;
  gemini) MODEL="openrouter/google/gemini-3.8-flash" ;;
  *) echo "pakai: $0 qwen|gemini" >&2; exit 1 ;;
esac

openclaw config set "agents.defaults.models[\"$MODEL\"]" '{}' --strict-json >/dev/null
openclaw config set agents.entries.merapi.model "{\"primary\":\"$MODEL\",\"fallbacks\":[]}" --strict-json >/dev/null
got="$(jq -r '.agents.entries.merapi.model.primary' ~/.openclaw/openclaw.json)"
[[ "$got" == "$MODEL" ]] || { echo "[set-model] gagal: model merapi = $got" >&2; exit 1; }
echo "[set-model] merapi -> $MODEL"
