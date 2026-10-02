# Daftar alamat web

Semua layanan berjalan di server `merapi`. Password tidak ditulis di sini; semuanya ada di `.env`.

## Bisa dibuka langsung dari laptop (lewat Tailscale)

Laptop harus tersambung ke Tailscale.

| Layanan | Alamat | Login |
|---|---|---|
| Medusa Admin (toko online) | http://100.97.181.49:9000/app | `MEDUSA_ADMIN_EMAIL` / `MEDUSA_ADMIN_PASSWORD` |
| Medusa Store API | http://100.97.181.49:9000/store/products | — |
| Grafana (dashboard "Ringkasan Agentic") | http://100.97.181.49:3000 | `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` |

## Hanya dari server (perlu SSH tunnel)

Layanan ini sengaja hanya terbuka di `127.0.0.1` server. Untuk membukanya dari laptop, jalankan dulu di laptop:

```bash
ssh -L 9090:127.0.0.1:9090 -L 9093:127.0.0.1:9093 -L 18789:127.0.0.1:18789 areph09@100.97.181.49
```

Selama terminal SSH itu terbuka, alamat di bawah bisa dibuka di browser laptop.

| Layanan | Alamat | Keterangan |
|---|---|---|
| Prometheus | http://localhost:9090 | Metrik, status target, dan alert rules (menu Alerts) |
| Alertmanager | http://localhost:9093 | Alert yang sedang aktif |
| OpenClaw Dashboard (Control UI) | http://localhost:18789 | Chat dengan agent dan lihat run. Login pertama: lihat di bawah |

**Login pertama ke OpenClaw Dashboard:** di server jalankan `openclaw dashboard --no-open`, lalu salin link sekali-pakai yang muncul ke browser laptop (tunnel harus aktif). Bila host di link berupa `127.0.0.1` atau `172.18.0.1`, ganti menjadi `localhost`. Setelah berhasil, browser itu tersimpan sebagai perangkat admin. Link kedaluwarsa dalam waktu singkat; jalankan ulang bila perlu. Sesi chat `main` masih memakai `openrouter/auto`; ketik `/model openrouter/qwen/qwen3.7-plus` sebelum mengobrol.

Layanan lain tanpa tampilan web (cukup dicek dari server):

| Layanan | Alamat di server | Keterangan |
|---|---|---|
| Loki | http://127.0.0.1:3100 | Log container; lebih mudah dilihat lewat Grafana → Explore |
| alert-bridge | http://127.0.0.1:5001/health | Status penerusan alert ke OpenClaw |

## Layanan luar

| Layanan | Alamat | Kegunaan |
|---|---|---|
| OpenRouter | https://openrouter.ai | Credits, batas pengeluaran, dan riwayat pemakaian (menu Activity) |
| Dokumentasi OpenClaw | https://docs.openclaw.ai | Juga tersedia offline di `~/.npm-global/lib/node_modules/openclaw/docs/` |
