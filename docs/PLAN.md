# Rencana pengerjaan — Agentic AI untuk Manajemen Server Berbasis Kontainer

Server: `merapi` (lihat `ENVIRONMENT.md`). Referensi lama (read-only): `~/reference/agentic-env/` dan `~/migration-backup/MIGRATION.md`. Kodenya boleh dipakai ulang, tetapi **data lama tidak di-restore dan secrets lama tidak disalin**.

Alur kerja: di akhir setiap stage, jalankan verifikasi stage tersebut, commit, perbarui status di file ini, tampilkan ringkasan, lalu **berhenti dan tunggu persetujuan**.

## Status

| Stage | Judul | Status | Tanggal selesai | Commit |
|---|---|---|---|---|
| 1 | Struktur repo | ✅ Selesai | 2026-09-29 | `Stage 1:` di git log |
| 2 | Layer 1: aplikasi target | ✅ Selesai | 2026-09-29 | `Stage 2:` di git log |
| 3 | Layer 2: observability | ✅ Selesai | 2026-09-29 | `Stage 3:` di git log |
| 4 | Alert rules per skenario | ⬜ Belum | — | — |
| 5 | Chaos scripts dan reset | ✅ Selesai (verifikasi alert menunggu Stage 4) | 2026-09-30 | `Stage 5:` di git log |
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

### Stage 2
- `docker-compose.yml` (project `agentic`) di root: `medusa-postgres`, `medusa-redis`, `medusa-app`, masing-masing dengan healthcheck. Semua image di-pin (lihat `docs/SETUP.md`).
- Aplikasi Medusa ditulis baru di `app/medusa` (Medusa 2.20.1, sama dengan referensi). Penyalinan langsung dari `~/reference` ditolak oleh pengaman izin otomatis, jadi `package.json`, config, dan seed ditulis ulang, dan lockfile dibuat baru dari npm.
- Entrypoint container: `db:migrate` → buat user admin (dari `.env`) → seed (idempoten, dilewati bila produk sudah ada) → `medusa start`. Seed pertama ±80 detik.
- **Keputusan desain:** Redis memakai `noeviction`, bukan `allkeys-lru` seperti di referensi. Dengan LRU, flood TC-03 akan meng-evict key milik Medusa dan memori tidak pernah benar-benar penuh. Dengan `noeviction`, memori terisi dan write aplikasi gagal (`OOM command not allowed`), yang menjadi gejala nyata yang harus ditangani agent.
- **Catatan untuk TC-01:** baseline idle sudah 12/50 koneksi, jadi 45 koneksi chaos akan menghabiskan pool (12 + 45 > 50). Script TC-01 perlu menangani koneksi yang ditolak (`too many clients`) sebagai hasil yang diharapkan.
- Verifikasi:
  - 3 container `healthy`.
  - `GET http://100.97.181.49:9000/app` → 200, login admin lewat API berhasil, `/admin/products` = 40 dan `/admin/orders` = 120.
  - `ss -tulpn`: `127.0.0.1:5432`, `127.0.0.1:6379`, `100.97.181.49:9000`. Port 9000 tidak terjangkau dari IP LAN.
  - Restart container: migrasi dan seed dilewati, `restarts=0`.

### Stage 3
- 9 service observability ditambahkan ke `docker-compose.yml`, semua image di-pin. Config ditulis baru di `observability/`.
- Exporter tidak dipublikasikan ke host. Prometheus (9090), Alertmanager (9093), dan Loki (3100) hanya di `127.0.0.1`. Grafana (3000) hanya di IP Tailscale, dengan login wajib (kredensial di `.env`).
- Alertmanager sementara memakai receiver `null`. Webhook ke alert-bridge ditambahkan di Stage 6. Folder `observability/prometheus/rules/` disiapkan untuk Stage 4.
- Dashboard dibuat sebagai JSON statis `observability/grafana/dashboards/ringkasan.json` (19 panel).
- Verifikasi:
  - Prometheus: 9/9 target `up`.
  - Loki berisi log dari 12 container. Lewat API query Grafana (`/api/ds/query`, datasource Loki), log `medusa-app`, `medusa-postgres`, dan `medusa-redis` muncul.
  - Datasource Prometheus dan Loki `OK`. Alertmanager bisa di-query lewat proxy Grafana; endpoint `/health` tidak didukung oleh tipe datasource ini, dan itu normal.
  - Akses Grafana tanpa login ditolak (401).
- **Catatan untuk Stage 4 (TC-01):** `pg_stat_activity_count` dari exporter hanya menghitung backend klien per database (idle ≈ 3–4). View `v_connection_usage` menghitung semua baris `pg_stat_activity`, termasuk proses latar belakang (±5) dan pool Medusa yang sedang aktif. Ambang TC-01 akan memakai metrik exporter. Perlu diingat pula bahwa 3 slot dicadangkan untuk superuser (`superuser_reserved_connections`).
- **Catatan:** Promtail sudah dinyatakan deprecated oleh Grafana (penggantinya Grafana Alloy). Tetap dipakai sesuai rencana, di-pin ke rilis terakhir 3.6.11. node_exporter berjalan di jaringan bridge, sehingga metrik jaringan yang dilaporkannya adalah milik namespace container, bukan host. CPU, memori, dan disk tetap milik host.

### Stage 5 (dimulai 2026-09-29, selesai 2026-09-30)
Dikerjakan lebih dulu daripada Stage 4 atas permintaan. Verifikasi "alert firing" diganti dengan pengecekan metrik Prometheus sampai rule Stage 4 tersedia.

**Sudah ada:**
- `chaos/common.py`: baca `.env`, tulis event JSONL (`ts_ms` epoch ms, `run_id`, `scenario`, `event`) ke `benchmark/runs/events.jsonl`, dan pidfile di `benchmark/runs/pids/`. `RUN_ID` bisa diberikan dari luar.
- `chaos/tc01_connection_pool_exhaustion.py`: 45 koneksi simultan dengan `application_name=chaos_tc01`. Koneksi ditahan sampai `--hold`, SIGTERM, atau diputus server.
- `chaos/tc02_deadlock_simulation.py`: dua transaksi dengan urutan kunci terbalik di skema terpisah `chaos`. Default 3 round.
- `chaos/tc03_redis_memory_flood.py`: 10.000 task × 24 KiB ke list `queue:chaos:tasks` (≈91% dari 256 MiB). Berhenti dengan rapi bila Redis menolak write (OOM).
- `chaos/tc04_container_kill.py`: `docker kill` `medusa-postgres` dan `medusa-redis`, lalu mengamati status selama 10 detik (termasuk apakah restart policy menghidupkannya kembali).
- `chaos/requirements.txt` (psycopg 3.3.6, redis 8.1.0). Dijalankan dengan `.venv/bin/python` (venv di root, di-ignore).
- `scripts/reset-env.sh`, berjalan sekitar 35 detik:
  1. Hentikan chaos lewat pidfile.
  2. Putus koneksi `chaos_%` dan drop skema `chaos`.
  3. Restart postgres dan redis (Redis kosong karena tanpa persistensi), lalu medusa.
  4. Tunggu semua healthy, metrik kembali ke baseline, dan tidak ada alert aktif di Prometheus maupun Alertmanager.
  5. Catat `reset_start` dan `reset_done` ke `events.jsonl`.

**Hasil uji:**
- `reset-env.sh` pada stack normal: semua cek lolos.
- TC-01: 43 koneksi terbuka dan 2 ditolak (`too many clients`). Exporter menunjukkan 46/50 (92%). `reset-env.sh` menghentikan script (`reason: signal`) dan stack kembali normal.
- **Temuan TC-01:** Medusa tetap melayani `/store/products` (200, <0,1 s) karena pool koneksinya sudah terbuka sebelum chaos. Dampaknya hanya ke koneksi baru.

**Hasil uji lanjutan (2026-09-30):**
- **TC-02:** 3 round, masing-masing satu transaksi menjadi `deadlock_victim` dan yang lain commit. `pg_stat_database_deadlocks` naik 0 → 3 (terlihat di Prometheus dalam ≤ 10 s), dan PostgreSQL mencatat 3 kali `deadlock detected` di log. Counter ini **tidak kembali ke 0** setelah reset karena statistik PostgreSQL bertahan saat restart, jadi alert harus memakai `increase()`, bukan nilai absolut.
- **TC-03:** 10.000 task masuk, memori Redis 92,5% (Prometheus sama), tanpa OOM. Dua bug diperbaiki:
  1. OOM di redis-py 8 muncul sebagai `OutOfMemoryError` tanpa kata "OOM" di pesannya.
  2. Payload 24 KiB + metadata jatuh ke kelas alokasi jemalloc 28 KiB, sehingga Redis penuh di task ke-9.274. Ukuran task kini dikunci 24.400 byte (`--item-bytes`).

  Pada 92,5%, Medusa masih bisa membuat cart. Pada 100% (uji OOM), `POST /store/carts` gagal 500 dengan `OOM command not allowed`, dan script mencatat `oom_error` tanpa crash.
- **TC-04:** kedua container `Exited (137)`, `restart_count=0` selama 20 s pengamatan. **`docker kill` tidak memicu restart policy `unless-stopped`**, jadi container tetap mati sampai dipulihkan dan time-to-action agent valid. `pg_up`/`redis_up` = 0, tetapi `up{job="postgres|redis"}` tetap 1 (yang di-scrape adalah exporter), sehingga alert TC-04 harus memakai `pg_up`/`redis_up` (atau cAdvisor). `/health` Medusa tetap 200 saat database mati; endpoint ini tidak mengecek dependensi.
- `reset-env.sh` dijalankan setelah setiap TC dan selalu kembali ke kondisi awal (40 produk, 120 pesanan, 0 key chaos, tidak ada alert).
- `benchmark/runs/events.jsonl` berisi 2 `inject_start` TC-03 tanpa `inject_done`, dari run yang crash sebelum perbaikan. File ini di-ignore git.

**Verifikasi yang ditunda:** "alert yang benar firing di Alertmanager" diuji ulang setelah rule Stage 4 ada.

**Keputusan yang masih terbuka:**
- Redis `noeviction` (sekarang) atau `allkeys-lru` (referensi).
- TC-01 dibiarkan seperti sekarang atau diperberat agar Medusa ikut terdampak.
- Stage 4 ditulis sendiri oleh pengguna atau dibuatkan draf.

**Setelah Stage 4:** uji ulang TC-01 sampai TC-04 untuk memastikan alert asli firing (dan sampai ke alert-bridge setelah Stage 6).
