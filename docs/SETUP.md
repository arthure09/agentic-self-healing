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

(diisi di Stage 3)

## alert-bridge

(diisi di Stage 6)
