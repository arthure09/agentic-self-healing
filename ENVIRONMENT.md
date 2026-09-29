# Lingkungan server `merapi`

Dicatat 2026-09-29 saat fondasi server disiapkan (sebelum stack aplikasi dideploy). Dipakai sebagai bahan Bab 3.

## 1. Perangkat keras

| Komponen | Spesifikasi |
|---|---|
| CPU | Intel Core i3-7100 @ 3.90 GHz (2 core, 4 thread, 1 socket) |
| RAM | 30 GiB (31.772.176 kB) |
| Swap | 8 GiB |
| Disk | `/` 455 GB (LVM `ubuntu-vg-1/ubuntu-lv`), `/boot` 2 GB, `/boot/efi` 1.1 GB |
| GPU | NVIDIA GeForce RTX 2080 Ti (TU102). Driver NVIDIA **belum terpasang** (saat ini memakai `nouveau`). Tidak dipakai untuk inferensi; LLM lokal berjalan di PC RTX 5090 |

## 2. Sistem operasi dan perangkat lunak

| Komponen | Versi | Sumber |
|---|---|---|
| OS | Ubuntu 26.04.1 LTS (resolute) | — |
| Kernel | 7.0.0-34-generic | — |
| Zona waktu | Asia/Jakarta (WIB, UTC+7), NTP aktif dan tersinkron | systemd-timesyncd |
| Docker Engine | 29.8.1 (`docker-ce 5:29.8.1-1~ubuntu.26.04~resolute`) | repo resmi download.docker.com |
| containerd | 2.3.6 | repo Docker |
| Docker Buildx | 0.37.1 | repo Docker |
| Docker Compose | v5.5.1 (plugin) | repo Docker |
| Docker: log driver | `json-file`, `max-size 10m`, `max-file 3` (`/etc/docker/daemon.json`) | — |
| Docker: storage / cgroup | overlayfs / systemd | — |
| Tailscale | 1.102.4 | repo Tailscale |
| ufw | 0.36.2 | arsip Ubuntu |
| OpenSSH | 10.2p1 | arsip Ubuntu |
| git | 2.53.0 (`init.defaultBranch=main`) | arsip Ubuntu |
| Python | 3.14.4, pip 25.1.1, python3-venv | arsip Ubuntu |
| tmux / curl / jq / htop | 3.6 / 8.18.0 / 1.8.1 / 3.4.1 | arsip Ubuntu |
| netcat | netcat-openbsd 1.234 | arsip Ubuntu |
| Node.js / npm | belum terpasang (dibutuhkan untuk OpenClaw) | — |
| OpenClaw | belum terpasang | — |

## 3. Jaringan

| Interface | Alamat |
|---|---|
| `enp2s0` (LAN) | 10.28.14.176/24 |
| `tailscale0` | 100.97.181.49 (hostname Tailscale `merapi`) |
| `docker0` | 172.17.0.1/16 |

### Tes jaringan ke PC RTX 5090 (10.28.14.200, LAN)

| Metrik | Hasil |
|---|---|
| `ping -c 10` | 10/10 diterima, 0% packet loss |
| RTT min / **avg** / max | 0.196 / **0.515** / 0.644 ms |
| Jitter (mdev) | **0.157 ms** |
| Port 11434 (Ollama) | **ditolak** (`Connection refused`). Host dapat dijangkau, tetapi belum ada layanan yang mendengarkan di port 11434 pada antarmuka LAN |

## 4. Firewall (ufw)

Status: aktif dan enabled. Logging `low`. Kebijakan default: **deny** masuk, **allow** keluar, **deny** routed.

| Aturan | Aksi | Dari |
|---|---|---|
| 22/tcp (OpenSSH), IPv4 dan IPv6 | ALLOW IN | Anywhere |
| Semua trafik di interface `tailscale0`, IPv4 dan IPv6 | ALLOW IN | Anywhere |

Artinya dari LAN hanya SSH yang terbuka. Semua layanan lain hanya bisa diakses lewat Tailscale, kecuali port yang dipublikasikan Docker (lihat catatan di bawah).

> **Catatan penting:** port yang dipublikasikan Docker (`ports: "5432:5432"` dan sejenisnya) **tidak difilter oleh ufw**. Docker menulis aturan iptables sendiri (rantai `DOCKER`) yang diproses sebelum aturan ufw. Untuk membatasi port layanan hanya ke Tailscale atau localhost, bind port secara eksplisit di compose (mis. `"127.0.0.1:5432:5432"` atau `"100.97.181.49:9090:9090"`), bukan lewat ufw.

## 5. Referensi dari server lama (`tandikat`)

Sumber: `~/migration-backup/MIGRATION.md` dan `project.tar.gz`, yang diekstrak read-only ke `~/reference/agentic-env/`. `secrets.tar.gz` tidak diekstrak.

### 5.1 Komponen yang bisa dipakai ulang

| Komponen | Isi | Yang perlu diperbaiki |
|---|---|---|
| `chaos-scripts/tc01_connection_pool_exhaustion.py` | Membuka 45 koneksi idle ke Postgres (`max_connections=50`) | DSN berisi password di-hardcode. Ganti ke `os.environ["PG_DSN"]`. Host `localhost:5432` hanya berlaku jika dijalankan di host |
| `chaos-scripts/tc02_deadlock_simulation.py` | Dua transaksi paralel saling mengunci baris `chaos_deadlock_demo` | DSN hardcoded (sama seperti TC-01). Tabel uji dibuat di DB produksi `medusa_db` |
| `chaos-scripts/tc03_redis_memory_flood.py` | Menyuntikkan 10.000 key `queue:chaos:*` masing-masing 20 KB | Host/port hardcoded. **Perlu diverifikasi:** 10.000 × 20 KiB ≈ 195 MiB ≈ 76% dari `maxmemory 256mb`, **di bawah** ambang alert 85%. Selain itu `allkeys-lru` akan meng-evict key (termasuk milik Medusa) sebelum memori benar-benar penuh. Parameter default atau policy Redis perlu disesuaikan |
| `chaos-scripts/tc04_container_kill.sh` | `docker kill medusa-postgres/medusa-redis` | Nama container hardcoded. **Perlu diverifikasi:** interaksi `docker kill` dengan `restart: unless-stopped`. Jika Docker menghidupkan ulang container sendiri, time-to-action agent tidak valid |
| `alert-bridge/` (Flask, python:3.12-slim) | Menerjemahkan webhook Alertmanager ke `POST /hooks/agent` OpenClaw, satu pesan per alert *firing* | Token dari env (baik), tetapi di compose di-hardcode. Tidak ada retry atau validasi token kosong. Endpoint webhook tanpa autentikasi dan port 5001 bind 0.0.0.0. Memakai server dev Flask. Timestamp di pesan diberi label "diterima agent" padahal diambil di alert-bridge, jadi perlu diluruskan untuk metrik penelitian. Alert *resolved* diabaikan |
| `alertmanager/alertmanager.yml` | Satu receiver webhook ke `alert-bridge:5001`, `group_wait 5s`, `group_interval 10s` | Siap pakai (DNS internal compose) |
| `prometheus/prometheus.yml` | Scrape 5 s ke exporter, cAdvisor, dan Prometheus sendiri | Siap pakai (nama service compose, tanpa IP) |
| `prometheus/alert_rules.yml` | 5 rule: TC-01, TC-02, TC-03, TC-04 (Postgres dan Redis), dengan label `scenario` dan `remediation_skill` | Siap pakai. Nama skill yang dirujuk belum ada (lihat 5.2) |
| `postgres/init.sql` | Ekstensi `uuid-ossp`, `pg_trgm`, view `v_connection_usage` | Siap pakai |
| `loki/`, `promtail/` | Loki TSDB v13 retensi 7 hari, Promtail via Docker SD | Promtail sudah deprecated oleh Grafana (penggantinya Grafana Alloy). Pertimbangkan migrasi |
| `docker-compose.yml` | 12 service (Layer 1 dan Layer 2 serta alert-bridge) | Secret di-hardcode: `POSTGRES_PASSWORD`, `DATABASE_URL`, `DATA_SOURCE_NAME`, `OPENCLAW_HOOK_TOKEN`, `GF_SECURITY_ADMIN_PASSWORD` (masih default). Semua port bind 0.0.0.0 (lihat catatan ufw). 8 image bertag `:latest` (pin ke digest di MIGRATION.md). `GF_AUTH_ANONYMOUS_ENABLED=true`. `version: "3.9"` sudah usang |
| `medusa/` | Dockerfile (node:20-alpine), `medusa-config.ts`, `.env.template` | `.env` asli (di `secrets.tar.gz`) berisi `ADMIN_CORS`/`AUTH_CORS` dengan IP lama 100.93.122.112 → ganti ke 100.97.181.49 |
| `README.md` | Panduan deploy | Masih menyebut `tandikat`/100.93.122.112, dan ada salah ketik 100.93.122.190 |

Data yang bisa di-restore: `data-medusa_db.sql.gz` (dump `medusa_db`) dan `data-grafana.db.gz` (dashboard dan datasource Grafana). Metrik Prometheus historis (3.3 GB) tidak di-backup.

### 5.2 Yang belum ada sama sekali

- **OpenClaw Gateway:** belum pernah dipasang. Belum ada config (`~/.openclaw`), hooks token, maupun unit systemd. Gateway harus listen di port 18789 dan dapat dijangkau dari container lewat `host.docker.internal`.
- **SKILL.md remediasi (4 buah):** `tc01-connection-pool-healing`, `tc02-deadlock-resolution`, `tc03-redis-memory-flood`, `tc04-container-recovery`.
- **Config model provider:** DeepSeek via Ollama (PC 5090; port 11434 belum terbuka di LAN), Qwen (DashScope), dan Gemini. Belum ada API key.
- **Bot Telegram** untuk audit dan notifikasi.
- **Repo git:** proyek lama tidak pernah di-version-control. Juga belum ada `.gitignore` root.
- **Node.js/npm** di server ini (prasyarat OpenClaw).
