# Rencana pengerjaan — Agentic AI untuk Manajemen Server Berbasis Kontainer

Server: `merapi` (lihat `ENVIRONMENT.md`). Referensi lama (read-only): `~/reference/agentic-env/` dan `~/migration-backup/MIGRATION.md`. Kodenya boleh dipakai ulang, tetapi **data lama tidak di-restore dan secrets lama tidak disalin**.

Alur kerja: di akhir setiap stage, jalankan verifikasi stage tersebut, commit, perbarui status di file ini, tampilkan ringkasan, lalu **berhenti dan tunggu persetujuan**.

## Status

| Stage | Judul | Status | Tanggal selesai | Commit |
|---|---|---|---|---|
| 1 | Struktur repo | ✅ Selesai | 2026-09-29 | `Stage 1:` di git log |
| 2 | Layer 1: aplikasi target | ⬜ Belum | — | — |
| 3 | Layer 2: observability | ⬜ Belum | — | — |
| 4 | Alert rules per skenario | ⬜ Belum | — | — |
| 5 | Chaos scripts dan reset | ⬜ Belum | — | — |
| 6 | alert-bridge | ⬜ Belum | — | — |

## Aturan umum

- Secrets hanya di `.env` (tidak di-commit). `.env.example` berisi placeholder.
- Semua image di-pin ke versi spesifik, tidak ada `:latest`.
- Docker melewati ufw: port internal di-bind ke `127.0.0.1`, UI (Medusa admin, Grafana) di-bind ke IP Tailscale saja.
- Minta konfirmasi sebelum `sudo`, menghapus volume/data, atau `git push`.
- Catat versi setiap komponen di `docs/SETUP.md` (untuk Bab 3).

## Stage 1 — Struktur repo

- `git init` (branch `main`), `.gitignore`, `.env.example`, `.env` dengan password acak (nilainya tidak ditampilkan).
- Struktur: `app/`, `observability/`, `alert-bridge/`, `chaos/`, `skills/`, `agent/`, `benchmark/`, `scripts/`, `docs/`.

**Verifikasi:** `git status` tidak menampilkan `.env`.

## Stage 2 — Layer 1: aplikasi target

- MedusaJS (backend + admin), PostgreSQL, dan Redis di docker-compose, masing-masing dengan healthcheck.
- PostgreSQL `max_connections=50` (untuk TC-01). Redis `maxmemory 256mb` (untuk TC-03).
- Seed data katalog produk dan pesanan contoh agar ada beban realistis.

**Verifikasi:** semua container healthy, Medusa admin bisa dibuka lewat IP Tailscale, dan `ss -tulpn` menunjukkan 5432 dan 6379 hanya di `127.0.0.1`.

## Stage 3 — Layer 2: observability

- Exporter: postgres_exporter, redis_exporter, cAdvisor, node_exporter.
- Prometheus, Alertmanager, Grafana (provisioning datasource + satu dashboard ringkasan), Loki + Promtail (log semua container).

**Verifikasi:** semua target Prometheus UP, log container muncul di Loki lewat Grafana.

## Stage 4 — Alert rules per skenario

Alert rules yang secara spesifik mendeteksi:

- **TC-01** connection pool exhaustion: koneksi aktif PostgreSQL mendekati `max_connections`.
- **TC-02** deadlock: kenaikan counter deadlock PostgreSQL.
- **TC-03** Redis memory flooding: pemakaian memori > 85% dari `maxmemory`.
- **TC-04** container down: container PostgreSQL atau Redis tidak berjalan / target down.

Setiap rule punya label `scenario` (`tc01`..`tc04`) dan annotation yang jelas. Pakai ulang dari referensi bila ada, lalu sesuaikan threshold dan `for:` agar deteksi terjadi dalam hitungan detik, bukan menit.

**Verifikasi:** `promtool check rules` lolos.

## Stage 5 — Chaos scripts dan reset

- `chaos/tc01`..`tc04` sesuai definisi proposal:
  - TC-01: 45 koneksi simultan ke PostgreSQL (max 50).
  - TC-02: dua transaksi saling mengunci baris yang sama (circular dependency).
  - TC-03: 10.000 task palsu ke antrean Redis sampai memori > 85% dari 256MB.
  - TC-04: hentikan paksa container PostgreSQL dan Redis.
- Semua kredensial diambil dari `.env`. Setiap script mencatat timestamp injeksi (epoch ms) ke `benchmark/runs/` dalam format JSONL.
- `scripts/reset-env.sh`: kembalikan stack ke kondisi awal yang identik (hentikan chaos, restart service, bersihkan antrean Redis, seed ulang bila perlu, tunggu semua healthy dan semua alert resolved).

**Verifikasi:** jalankan setiap TC satu kali TANPA agen. Pastikan alert yang benar firing di Alertmanager, lalu `reset-env.sh` mengembalikan semuanya normal.

## Stage 6 — alert-bridge

- Porting dari referensi. Menerima webhook Alertmanager, mencatat timestamp alert diterima (epoch ms) ke JSONL, lalu meneruskan ke endpoint OpenClaw (konfigurasi via env).
- Kalau OpenClaw belum ada atau gagal, catat ke log dan jangan crash. Sediakan endpoint health.
- Jalankan sebagai container di stack yang sama.

**Verifikasi:** jalankan TC-04, lalu pastikan alert tercatat di log alert-bridge dengan timestamp.

## Catatan per stage

### Stage 1
- Repo `main` dibuat di `~/skripsi/agentic-server-mgmt`. `ENVIRONMENT.md` tetap di root.
- `.env` (mode 600) berisi secret acak `openssl rand -hex 24`: password Postgres, JWT/cookie secret Medusa, password admin Medusa, password admin Grafana, token hook OpenClaw.
- `.env.example` berisi placeholder `CHANGE_ME`. `benchmark/runs/*` di-ignore karena berisi data run mentah.
- Folder kosong dijaga dengan `.gitkeep`.
- Verifikasi: `git status --ignored` menandai `.env` sebagai `!!` (ignored), dan `.env` tidak ada di daftar file yang di-commit.
- Catatan: `CLAUDE.md` yang disebut di instruksi tidak ditemukan. Konteks diambil dari `ENVIRONMENT.md` dan `~/migration-backup/MIGRATION.md`.
