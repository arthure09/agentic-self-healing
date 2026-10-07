#!/usr/bin/env bash
# Salin 4 skill TC dari repo (sumber utama) ke workspace agent merapi, karena
# agent memakai tools.fs.workspaceOnly=true dan hanya bisa membaca file di
# workspace. Salinan lama dihapus lalu disalin ulang, jadi aman dijalankan
# berkali-kali. Jalankan ulang setiap kali skills/*/SKILL.md di repo diubah.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${MERAPI_SKILLS_DIR:-$HOME/.openclaw/workspace-merapi/skills}"
SKILLS=(tc01-connection-pool-healing tc02-deadlock-resolution tc03-redis-memory-flood tc04-container-recovery)

mkdir -p "$DEST"
for s in "${SKILLS[@]}"; do
  [[ -f "$ROOT/skills/$s/SKILL.md" ]] || { echo "[sync-skills] tidak ada: skills/$s/SKILL.md" >&2; exit 1; }
  rm -rf "${DEST:?}/$s"
  cp -r "$ROOT/skills/$s" "$DEST/$s"
  diff -r "$ROOT/skills/$s" "$DEST/$s" >/dev/null
  echo "[sync-skills] OK: $s"
done
