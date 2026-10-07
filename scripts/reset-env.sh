#!/usr/bin/env bash
# Kembalikan stack ke kondisi awal yang identik sebelum setiap run pengujian:
#   0. salin skill ke workspace agent (sync-skills.sh) dan catat event run_config
#      (sha256 SKILL.md, AGENTS.md, openclaw.json; PROMPT_LEVEL .env & alert-bridge)
#   1. hentikan chaos script yang masih berjalan (pidfile)
#   2. putus koneksi chaos di PostgreSQL, bersihkan tabel uji TC-02
#   3. restart PostgreSQL, Redis (tanpa persistensi -> kosong), lalu Medusa
#      (entrypoint Medusa men-seed ulang bila katalog kosong)
#   4. tunggu semua container healthy, metrik kembali ke baseline, dan tidak
#      ada alert yang firing/pending
# Setiap reset dicatat ke benchmark/runs/events.jsonl (scenario "reset").
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
set -a; . ./.env; set +a

EVENTS="benchmark/runs/events.jsonl"
PID_DIR="benchmark/runs/pids"
TIMEOUT="${RESET_TIMEOUT:-300}"
RUN_ID="${RUN_ID:-reset-$(date -u +%Y%m%dT%H%M%SZ)}"
PROM="http://127.0.0.1:9090"
AM="http://127.0.0.1:9093"

mkdir -p "$(dirname "$EVENTS")"
now_ms() { date +%s%3N; }
event() {  # event <nama> [json-tambahan]
  local extra="${2:-}"; [[ -n "$extra" ]] || extra='{}'
  jq -cn --argjson ts "$(now_ms)" --arg run "$RUN_ID" --arg ev "$1" \
    --arg host "$(hostname)" --argjson extra "$extra" \
    '{ts_ms:$ts, run_id:$run, scenario:"reset", event:$ev, host:$host} + $extra' \
    | tee -a "$EVENTS"
}
log() { echo "[reset] $*" >&2; }
psql_q() { docker exec -e PGOPTIONS="-c client_min_messages=warning" medusa-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "$1"; }
prom_q() { curl -sf "$PROM/api/v1/query" --data-urlencode "query=$1" | jq -r '.data.result[0].value[1] // "0"'; }

healthy() { [[ "$(docker inspect -f '{{.State.Health.Status}}' "$1" 2>/dev/null)" == healthy ]]; }
prom_lt() { awk -v v="$(prom_q "$1")" -v t="$2" 'BEGIN{exit !(v < t)}'; }
prom_eq() { [[ "$(prom_q "$1")" == "$2" ]]; }
no_prom_alerts() { [[ "$(curl -sf "$PROM/api/v1/query" --data-urlencode 'query=ALERTS' | jq '.data.result | length')" == 0 ]]; }
no_am_alerts() { [[ "$(curl -sf "$AM/api/v2/alerts?active=true&silenced=false&inhibited=false" | jq length)" == 0 ]]; }

wait_until() {  # wait_until <deskripsi> <perintah...>  (perintah dievaluasi ulang tiap 2 s)
  local desc="$1"; shift
  local start=$SECONDS
  until "$@" >/dev/null 2>&1; do
    if (( SECONDS - start > TIMEOUT )); then
      log "TIMEOUT menunggu: $desc"
      event reset_failed "$(jq -cn --arg d "$desc" '{waiting_for:$d}')" >/dev/null
      exit 1
    fi
    sleep 2
  done
  log "OK: $desc ($((SECONDS - start)) s)"
}

event reset_start >/dev/null

# 0. Skill agent dibaca dari salinan di workspace (tools.fs.workspaceOnly), jadi
#    selaraskan dulu dengan repo, lalu catat konfigurasi agent untuk run ini.
scripts/sync-skills.sh >&2
OC="$HOME/.openclaw"
sha() { sha256sum "$1" | cut -d' ' -f1; }
skills_json="{}"
for f in "$OC"/workspace-merapi/skills/*/SKILL.md; do
  skills_json="$(jq -c --arg k "$(basename "$(dirname "$f")")" --arg v "$(sha "$f")" '. + {($k): $v}' <<<"$skills_json")"
done
bridge="$(curl -sf -m 5 http://127.0.0.1:5001/health || echo '{}')"
event run_config "$(jq -cn --argjson skills "$skills_json" \
  --arg agents "$(sha "$OC/workspace-merapi/AGENTS.md")" --arg oc "$(sha "$OC/openclaw.json")" \
  --arg env_level "${PROMPT_LEVEL:-}" --argjson bridge "$bridge" \
  '{skill_sha256:$skills, agents_md_sha256:$agents, openclaw_json_sha256:$oc,
    prompt_level_env:$env_level, prompt_level_bridge:$bridge.prompt_level, bridge_agent_id:$bridge.agent_id}')" >/dev/null

# 1. Hentikan chaos script yang masih berjalan
killed=()
if [[ -d "$PID_DIR" ]]; then
  for f in "$PID_DIR"/*.pid; do
    [[ -e "$f" ]] || continue
    pid="$(cat "$f")"
    if kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" && killed+=("$(basename "$f" .pid):$pid")
      for _ in $(seq 1 10); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
      kill -KILL "$pid" 2>/dev/null || true
    fi
    rm -f "$f"
  done
fi
log "chaos dihentikan: ${killed[*]:-(tidak ada)}"

# 2. Pastikan Layer 1 berjalan (setelah TC-04 container bisa dalam kondisi exited)
docker compose up -d postgres redis >/dev/null 2>&1
wait_until "postgres healthy" healthy medusa-postgres
psql_q "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE application_name LIKE 'chaos_%'" >/dev/null
psql_q "DROP SCHEMA IF EXISTS chaos CASCADE" >/dev/null

# 3. Restart berurutan: Medusa berhenti dulu agar tidak menulis ke Redis/DB
log "restart postgres, redis, medusa..."
docker compose stop medusa >/dev/null 2>&1
docker compose restart postgres redis >/dev/null 2>&1
wait_until "postgres healthy" healthy medusa-postgres
wait_until "redis healthy" healthy medusa-redis
docker compose start medusa >/dev/null 2>&1
wait_until "medusa healthy" healthy medusa-app

# 4. Verifikasi kondisi awal
products="$(psql_q 'SELECT count(*) FROM product WHERE deleted_at IS NULL')"
orders="$(psql_q 'SELECT count(*) FROM "order"')"
[[ "$products" -eq 40 ]] || { log "katalog tidak sesuai seed ($products produk)"; exit 1; }
chaos_keys="$(docker exec medusa-redis redis-cli --scan --pattern 'queue:chaos:*' | wc -l)"
[[ "$chaos_keys" -eq 0 ]] || { log "masih ada $chaos_keys key chaos di Redis"; exit 1; }

wait_until "exporter postgres & redis up" \
  prom_eq 'min(up{job=~"postgres|redis"}) * min(pg_up) * min(redis_up)' 1
wait_until "koneksi PostgreSQL < 50%" \
  prom_lt 'sum(pg_stat_activity_count) / scalar(pg_settings_max_connections)' 0.5
wait_until "memori Redis < 10%" prom_lt 'redis_memory_used_bytes / redis_memory_max_bytes' 0.1
wait_until "tidak ada alert firing/pending di Prometheus" no_prom_alerts
wait_until "tidak ada alert aktif di Alertmanager" no_am_alerts

event reset_done "$(jq -cn --argjson p "$products" --argjson o "$orders" \
  --arg k "${killed[*]:-}" '{products:$p, orders:$o, chaos_killed:$k}')" >/dev/null
log "selesai: stack kembali ke kondisi awal ($products produk, $orders pesanan)"
