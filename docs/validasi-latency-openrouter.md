# Validasi arti `latency` OpenRouter (2026-10-13)

**Pertanyaan:** apakah kolom `latency` di `/api/v1/generation` OpenRouter bisa dipakai sebagai TTFT (waktu sampai token pertama)? Dokumentasi menyebutnya "Total latency in milliseconds" ([Get a generation](https://openrouter.ai/docs/api/api-reference/generations/get-generation)).

## Cara uji

- Skrip `scripts/validasi_latency_openrouter.py`, di luar jalur OpenClaw. Konfigurasi agent dan benchmark tidak diubah.
- 10 permintaan streaming ke `qwen/qwen3.7-plus`, `reasoning: {effort: "low"}` (sama dengan thinking `low` di batch), temperature tidak dikirim (sama dengan batch). Prompt sama setiap kali: "Jelaskan dalam tiga kalimat apa itu connection pool pada PostgreSQL." Jeda 1 s antarpermintaan.
- Dicatat dari sisi merapi: waktu kirim, chunk pertama berisi token (reasoning atau teks), chunk pertama berisi teks jawaban, dan waktu selesai (stream habis). Setelah 60 s, data `/api/v1/generation` diambil untuk ke-10 gen-ID.
- Semua dilayani Alibaba, model `qwen/qwen3.7-plus-20260602`, `streamed: true`. Data mentah: `benchmark/openrouter/validasi-latency-20261013T153831.jsonl`.

## Hasil

Waktu diukur dari saat permintaan dikirim (ms). Selisih = ukuran merapi − angka OpenRouter.

| # | gen-ID (akhir) | Chunk token pertama | `latency` | Selisih | Selesai | `generation_time` | Selisih | `latency` + `generation_time` | Token output (reasoning) | Chunk teks jawaban pertama |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `GznFDAAZ` | 1.551 | 1.044 | +507 | 24.425 | 23.882 | +543 | 24.926 | 1.768 (1.242) | 22.823 |
| 2 | `zp5oLeGW` | 1.530 | 1.301 | +229 | 23.465 | 23.152 | +313 | 24.453 | 1.614 (1.205) | 22.028 |
| 3 | `sbSbXAi5` | 880 | 738 | +142 | 26.845 | 26.696 | +149 | 27.434 | 1.948 (1.420) | 25.702 |
| 4 | `EnU3azXb` | 995 | 827 | +168 | 16.350 | 16.167 | +183 | 16.994 | 1.130 (802) | 14.783 |
| 5 | `NRCdYepR` | 1.276 | 1.126 | +150 | 25.927 | 25.708 | +219 | 26.834 | 1.840 (1.363) | 24.554 |
| 6 | `pqHYtrnU` | 1.210 | 1.086 | +124 | 21.548 | 21.401 | +147 | 22.487 | 1.491 (1.095) | 19.916 |
| 7 | `Ro5u4Ugd` | 1.018 | 859 | +159 | 23.822 | 23.637 | +185 | 24.496 | 1.604 (1.192) | 22.204 |
| 8 | `pZSzluxT` | 1.740 | 1.602 | +138 | 18.751 | 18.605 | +146 | 20.207 | 1.215 (897) | 17.379 |
| 9 | `63dw9zzg` | 1.422 | 1.217 | +205 | 23.724 | 23.482 | +242 | 24.699 | 1.593 (1.203) | 22.131 |
| 10 | `GmmenaVF` | 1.305 | 1.144 | +161 | 22.134 | 21.891 | +243 | 23.035 | 1.564 (1.139) | 20.744 |

Ringkasan selisih, median (min–maks):
- Chunk token pertama − `latency`: **+160 ms (+124 sampai +507)**
- Selesai − `generation_time`: **+202 ms (+146 sampai +543)**
- Selesai − (`latency` + `generation_time`): −904 ms (−1.456 sampai −501). Penjumlahan keduanya selalu **melebihi** durasi nyata.

## Kesimpulan

- **`latency` = waktu sampai token pertama (TTFT), bukan total.** Angkanya selalu ±0,16 s lebih kecil daripada waktu chunk pertama yang diterima merapi. Selisih kecil dan stabil ini wajar sebagai perjalanan jaringan OpenRouter → merapi.
- **`generation_time` = seluruh durasi panggilan**, dari permintaan masuk sampai token terakhir. Ini sudah **termasuk** `latency`. Selisihnya dengan waktu selesai di merapi juga hanya ±0,2 s.
- Jadi `latency` **bisa dipakai sebagai TTFT** versi OpenRouter, dengan dua catatan:
  1. Nilainya ±0,1–0,5 s lebih kecil daripada TTFT yang dirasakan klien (OpenClaw), karena perjalanan jaringan ke merapi tidak ikut terhitung.
  2. "Token pertama" di sini adalah token **reasoning (thinking)**, bukan teks jawaban. Teks jawaban baru muncul setelah model selesai berpikir: di uji ini 14,8–25,7 s.
- Akibat untuk rumus token/detik: `tokens_completion` ÷ `generation_time` ikut menghitung waktu tunggu token pertama. Untuk kecepatan menghasilkan token saja, gunakan `tokens_completion` ÷ (`generation_time` − `latency`).
- Data batch cocok dengan hasil ini. Di qwen-full-1 (661 panggilan), `generation_time` hanya ±0,2 s lebih pendek daripada lama giliran yang dicatat OpenClaw, dan `latency` < `generation_time` di semua panggilan. Lihat `docs/cek-openrouter-2026-10-13.md`.
- Batasan uji: hanya 10 permintaan, satu prompt pendek tanpa tool, satu waktu (13 Okt sore), satu penyedia (Alibaba). Saat batch, konteksnya lebih panjang dan ada pemanggilan tool. Belum diuji untuk Gemini.

## Ollama (untuk DeepSeek lokal nanti)

Dicek dari kode OpenClaw 2026.9.7 (`dist/`) dan dokumentasi `docs/providers/ollama*`, tanpa menjalankan Ollama.

- OpenClaw memakai API native Ollama (`/api/chat`), yang mengirim `total_duration`, `load_duration`, `prompt_eval_duration`, dan `eval_duration`.
- **Giliran agent biasa** (`dist/stream.runtime-*.mjs`): yang disimpan ke `usage` transkrip hanya **jumlah token**, yaitu `prompt_eval_count` → input, `eval_count` → output, `prompt_eval_cached_count` → cache. **Keempat field durasi tidak disimpan** (kata "_duration" tidak muncul di file itu). Biaya dicatat 0.
- Hanya fitur terpisah **node-inference** (`dist/node-inference-*.mjs`, perintah inferensi lewat node host, bukan giliran agent) yang membaca `load_duration` dan `total_duration` menjadi `timings: {loadMs, totalMs}`. Fitur ini pun tidak membaca `prompt_eval_duration` dan `eval_duration`.
- Yang tetap tersedia di transkrip untuk Ollama: waktu mulai dan selesai setiap giliran (`message.timestamp` dan timestamp event), sehingga durasi ujung ke ujung per giliran bisa dihitung seperti untuk OpenRouter.
- Artinya, TTFT dan kecepatan murni Ollama **tidak bisa** didapat dari transkrip OpenClaw. Perlu sumber lain, misalnya proxy pencatat antara OpenClaw dan Ollama, atau pemanggilan langsung ke Ollama di luar OpenClaw.
