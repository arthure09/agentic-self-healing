# Versi komponen (bahan Bab 3)

Dicatat per stage di server `merapi`. Detail perangkat keras, jaringan, dan firewall ada di `../ENVIRONMENT.md`.

## Host

| Komponen | Versi | Dicatat |
|---|---|---|
| OS | Ubuntu 26.04.1 LTS | Stage 1, 2026-09-29 |
| Kernel | 7.0.0-34-generic | Stage 1, 2026-09-29 |
| Docker Engine | 29.8.1 | Stage 1, 2026-09-29 |
| Docker Compose | 5.5.1 (plugin) | Stage 1, 2026-09-29 |
| git | 2.53.0 | Stage 1, 2026-09-29 |
| Python | 3.14.4 | Stage 1, 2026-09-29 |
| OpenSSL (pembuatan secret `.env`) | 3.5.5 | Stage 1, 2026-09-29 |
| Node.js | 24.21.0 (`nodejs 24.21.0-1nodesource1`, repo NodeSource `setup_24.x`), npm 11.19.0. Node 22 dari arsip Ubuntu tidak dipakai karena OpenClaw 2026.9.7 butuh `>=24.16.0` | Persiapan Layer 3, 2026-09-30 (dipasang pengguna) |
| OpenClaw | 2026.9.7 (commit `c074824`), `npm install -g openclaw@2026.9.7` **tanpa sudo** ke prefix user `~/.npm-global` (PATH ditambahkan di `~/.bashrc`). npm 11 memblokir install script secara default, jadi dipasang dengan `--allow-scripts=@google/genai,esbuild,koffi,protobufjs,openclaw`. Ukuran ±735 MB. Dikonfigurasi di Stage 7 (lihat bagian OpenClaw di bawah) | Persiapan Layer 3, 2026-09-30 |

## Layer 1 — aplikasi target

| Komponen | Versi / image | Catatan | Dicatat |
|---|---|---|---|
| PostgreSQL | `postgres:16.15-alpine3.24` (16.15) | `max_connections=50`, `shared_buffers=128MB`, `log_lock_waits=on`, `deadlock_timeout=1s`. Port `127.0.0.1:5432` | Stage 2, 2026-09-29 |
| Redis | `redis:7.4.11-alpine3.21` (7.4.11) | `maxmemory 256mb`, `maxmemory-policy noeviction`, tanpa persistensi. Port `127.0.0.1:6379` | Stage 2, 2026-09-29 |
| MedusaJS | 2.20.1 (backend + admin dashboard), image lokal `agentic/medusa:2.20.1` | Event bus, workflow engine, dan locking memakai Redis. Port `100.97.181.49:9000` (admin di `/app`) | Stage 2, 2026-09-29 |
| Node.js (dalam image Medusa) | `node:22.23.3-alpine3.24` (v22.23.3), npm 10.9.9 | Dependensi dikunci dengan `app/medusa/package-lock.json` | Stage 2, 2026-09-29 |

**Data seed** (`app/medusa/src/scripts/seed.ts`, deterministik dengan PRNG ber-seed tetap):
region Indonesia (IDR), 1 gudang (stok 1.000 per varian), 2 opsi pengiriman, 5 kategori, 40 produk / 69 varian, 30 pelanggan tamu, 120 pesanan yang dibuat lewat alur checkout Medusa (cart → shipping → payment `pp_system_default` → complete).

**Baseline idle:** 12 koneksi PostgreSQL aktif (24% dari 50) dengan Medusa berjalan tanpa beban; Redis ~2 MB.

## Layer 2 — observability

| Komponen | Image | Akses | Dicatat |
|---|---|---|---|
| postgres_exporter | `prometheuscommunity/postgres-exporter:v0.20.1` | internal (jaringan compose) | Stage 3, 2026-09-29 |
| redis_exporter | `oliver006/redis_exporter:v1.92.1` | internal | Stage 3, 2026-09-29 |
| cAdvisor | `gcr.io/cadvisor/cadvisor:v0.55.1` (housekeeping 5 s) | internal | Stage 3, 2026-09-29 |
| node_exporter | `prom/node-exporter:v1.12.1` (`pid: host`, rootfs `/host`) | internal | Stage 3, 2026-09-29 |
| Prometheus | `prom/prometheus:v3.15.0` (scrape & evaluasi 5 s, retensi 30 hari) | `127.0.0.1:9090` | Stage 3, 2026-09-29 |
| Alertmanager | `prom/alertmanager:v0.34.1` | `127.0.0.1:9093` | Stage 3, 2026-09-29 |
| Loki | `grafana/loki:3.7.8` (TSDB schema v13, filesystem, retensi 7 hari) | `127.0.0.1:3100` | Stage 3, 2026-09-29 |
| Promtail | `grafana/promtail:3.6.11` (Docker service discovery, refresh 5 s) | internal | Stage 3, 2026-09-29 |
| Grafana | `grafana/grafana:13.2.3` | `100.97.181.49:3000` (login wajib, anonim nonaktif) | Stage 3, 2026-09-29 |

**Target scrape Prometheus (9):** prometheus, alertmanager, postgres, redis, cadvisor, node, loki, promtail, grafana.

**Grafana:** datasource Prometheus, Loki, dan Alertmanager diprovisioning dari `observability/grafana/provisioning/`. Dashboard `Ringkasan Agentic` (uid `agentic-ringkasan`, folder `Agentic`, halaman beranda) berisi stat per skenario TC-01–TC-04, grafik PostgreSQL/Redis, status container, CPU/memori per container dan host, serta panel log aplikasi target dari Loki.

**Label log Loki:** `container`, `service` (nama service compose), `project`, `stream`.

**Akses UI internal** (Prometheus/Alertmanager hanya di localhost): lewat tunnel SSH, mis. `ssh -L 9090:127.0.0.1:9090 -L 9093:127.0.0.1:9093 areph09@100.97.181.49`, atau lewat Grafana Explore.

## Chaos tooling (Stage 5)

| Komponen | Versi | Catatan | Dicatat |
|---|---|---|---|
| Python venv (`.venv/`) | Python 3.14.4 | dibuat dari `chaos/requirements.txt` | Stage 5, 2026-09-30 |
| psycopg | 3.3.6 (`psycopg[binary]`) | klien PostgreSQL untuk TC-01, TC-02 | Stage 5, 2026-09-30 |
| redis-py | 8.1.0 | klien Redis untuk TC-03 | Stage 5, 2026-09-30 |

Parameter default: TC-01 45 koneksi ditahan 600 s; TC-02 3 deadlock dengan jeda 2 s; TC-03 10.000 task × 24.400 byte (≈92% dari 256 MiB); TC-04 `docker kill` `medusa-postgres` dan `medusa-redis`. Durasi `reset-env.sh` ±35 s.

## alert-bridge (Stage 6)

| Komponen | Versi / image | Akses | Dicatat |
|---|---|---|---|
| alert-bridge | image lokal `agentic/alert-bridge:1.0.1` (1.0.0 di Stage 6; 1.0.1 di Stage 8: `deliver: false`) dari `python:3.13.15-slim-trixie`, hanya pustaka standar Python | `127.0.0.1:5001` (`POST /alertmanager`, `GET /health`) | Stage 6, 2026-09-30 |
| Alertmanager receiver | webhook `http://alert-bridge:5001/alertmanager`, `send_resolved: true`, `group_by [alertname, scenario]`, `group_wait 0s` | — | Stage 6, 2026-09-30 |

**Log:** `benchmark/runs/alerts.jsonl` (bind mount `/data`, ditulis sebagai uid 1000). Event yang dicatat:
- `alert_received`: setiap alert firing/resolved, dengan field `bridge_received_ms`, `starts_at_ms`, `ends_at_ms`, `alert_to_bridge_ms`, dan `first_seen`.
- `forward_ok`: `forward_sent_ms`, `forward_done_ms`, `http_status`.
- `forward_failed`: `attempts`, `error`, `gave_up_ms`.
- `forward_skipped`: token atau URL belum diisi.

**Penerusan ke OpenClaw:** `POST $OPENCLAW_HOOK_URL` dengan `Authorization: Bearer $OPENCLAW_HOOK_TOKEN`, body `{message, agentId, name, deliver: false}` (Stage 8; sebelumnya `true`). Hanya alert firing yang diteruskan, sekali per `(fingerprint, startsAt)`. Satu thread per alert, 3 percobaan (timeout 10 s, jeda 1 s dan 2 s).

## OpenClaw Gateway (Stage 7)

| Komponen | Nilai | Dicatat |
|---|---|---|
| Config | `~/.openclaw/openclaw.json` (di luar repo; dibuat oleh `openclaw onboard`, Custom setup, mode Local) | Stage 7, 2026-10-02 |
| Agent | id `merapi`, workspace `~/.openclaw/workspace` (terpisah dari repo) | Stage 7, 2026-10-02 |
| Model | `openrouter/qwen/qwen3.7-plus` lewat provider `openrouter` bawaan, kunci dari `OPENROUTER_API_KEY` (`.env`). Harga OpenRouter 2026-10-02: $0,32 input / $1,28 output per 1 juta token | Stage 7, 2026-10-02 |
| Gateway | port 18789, Tailscale off, secret Gateway plaintext dibuat otomatis. Stage 7: bind loopback. **Stage 8: `gateway.bind=custom`, `gateway.customBindHost=172.18.0.1`** → listening di `127.0.0.1` dan `172.18.0.1` saja | Stage 7–8, 2026-10-02 |
| Service | systemd **user** `~/.config/systemd/user/openclaw-gateway.service` (runtime Node, `--max-old-space-size=8192`), lingering aktif untuk `areph09`. Log: `journalctl --user -u openclaw-gateway` dan `/tmp/openclaw/openclaw-YYYY-MM-DD.log` | Stage 7, 2026-10-02 |
| Hooks | `hooks.enabled=true`, `path=/hooks`, `allowedAgentIds=["merapi"]`, token = `OPENCLAW_HOOK_TOKEN` (`.env`) | Stage 7, 2026-10-02 |
| Tugas latar dimatikan | `agents.defaults.heartbeat.every="0m"`, `plugins.entries.memory-core.config.dreaming.enabled=false`, `skills.workshop.autonomous.mode=off` | Stage 7, 2026-10-02 |
| Dilewati saat onboarding | channel chat, web search, skill dependencies, optional plugins, import memory | Stage 7, 2026-10-02 |
| Exec agent | `tools.exec.security=deny` (sementara, semua perintah host ditolak; default OpenClaw adalah `full`/`ask=off`). Diganti allowlist di Stage 9 | Stage 8, 2026-10-02 |

## Jaringan alert-bridge → OpenClaw (Stage 8)

| Komponen | Nilai | Dicatat |
|---|---|---|
| Jaringan compose | `agentic_agentic-net`, subnet `172.18.0.0/16`, gateway `172.18.0.1`, interface host `br-60cc89f9f66f` (dibuat otomatis Docker; berubah bila jaringan dibuat ulang, misalnya `docker compose down`) | Stage 8, 2026-10-02 |
| ufw | `sudo ufw allow in on br-60cc89f9f66f from 172.18.0.0/16 to 172.18.0.1 port 18789 proto tcp comment 'OpenClaw dari agentic-net'` | Stage 8, 2026-10-02 |
| `.env` | `OPENCLAW_HOOK_URL=http://172.18.0.1:18789/hooks/agent`, `OPENCLAW_AGENT_ID=merapi` | Stage 8, 2026-10-02 |
