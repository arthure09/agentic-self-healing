# Daftar alamat web

Semua layanan berjalan di server `merapi`. Password dan IP tidak ditulis di sini; semuanya ada di `.env` (`<TAILSCALE_IP>` = nilai `TAILSCALE_IP`).

## Bisa dibuka langsung dari laptop (lewat Tailscale)

Laptop harus tersambung ke Tailscale.

| Layanan | Alamat | Login |
|---|---|---|
| Medusa Admin (toko online) | http://<TAILSCALE_IP>:9000/app | `MEDUSA_ADMIN_EMAIL` / `MEDUSA_ADMIN_PASSWORD` |
| Medusa Store API | http://<TAILSCALE_IP>:9000/store/products | — |
| Grafana (dashboard "Ringkasan Agentic") | http://<TAILSCALE_IP>:3000 | `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` |

## Hanya dari server (perlu SSH tunnel)

Layanan ini sengaja hanya terbuka di `127.0.0.1` server. Untuk membukanya dari laptop, jalankan dulu di laptop:

```bash
ssh -L 9090:127.0.0.1:9090 -L 9093:127.0.0.1:9093 -L 18789:127.0.0.1:18789 -L 8090:127.0.0.1:8090 areph09@<TAILSCALE_IP>
```

Selama terminal SSH itu terbuka, alamat di bawah bisa dibuka di browser laptop.

| Layanan | Alamat | Keterangan |
|---|---|---|
| Prometheus | http://localhost:9090 | Metrik, status target, dan alert rules (menu Alerts) |
| Alertmanager | http://localhost:9093 | Alert yang sedang aktif |
| OpenClaw Dashboard (Control UI) | http://localhost:18789 | Chat dengan agent dan lihat run. Login pertama: lihat di bawah |
| Benchmark (jalankan batch dan lihat hasil) | http://localhost:8090 | Login `admin` / `BENCH_WEB_PASSWORD`. Di VSCode Remote-SSH cukup forward port 8090 (tab Ports). Service: `systemctl --user status benchmark-web` |

**Login pertama ke OpenClaw Dashboard:** di server jalankan

```bash
openclaw dashboard --json | python3 -c 'import sys,json; print(json.load(sys.stdin)["browserUrl"])'
```

lalu salin link sekali-pakai yang muncul ke browser laptop (tunnel harus aktif; ganti `127.0.0.1` menjadi `localhost` bila perlu). `openclaw dashboard --no-open` tidak mencetak link ini karena server tidak punya clipboard. Setelah berhasil, browser itu tersimpan sebagai perangkat admin. Link kedaluwarsa dalam waktu singkat; jalankan ulang bila perlu. Jangan bagikan link ini, karena berfungsi sebagai kunci admin. Sesi chat `main` masih memakai `openrouter/auto`; ketik `/model openrouter/qwen/qwen3.7-plus` sebelum mengobrol.

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
