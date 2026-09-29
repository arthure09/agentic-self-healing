#!/bin/sh
# Migrasi skema, buat user admin, seed data (idempoten), lalu jalankan server.
set -e
cd /server

npx medusa db:migrate

# Gagal bila user sudah ada; itu kondisi normal saat container di-restart.
npx medusa user -e "$MEDUSA_ADMIN_EMAIL" -p "$MEDUSA_ADMIN_PASSWORD" >/dev/null 2>&1 \
  && echo "[entrypoint] User admin dibuat." \
  || echo "[entrypoint] User admin sudah ada."

# seed.ts melewati dirinya sendiri bila produk sudah ada.
npx medusa exec ./src/scripts/seed.js

exec npx medusa start
