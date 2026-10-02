# Level prompt — noob, medium, pro

Keputusan dosen (bimbingan, dicatat 2026-10-02): pengujian memakai **tiga level prompt**, yaitu **noob**, **medium**, dan **pro**.

Level menggambarkan **keahlian orang yang menulis prompt**. Agent, model, skill, tool, dan guardrail sama untuk semua level. Yang diukur adalah seberapa baik agent bekerja ketika prompt makin kurang jelas.

## Definisi

| Level | Gaya | Isi |
|---|---|---|
| Noob | Bahasa awam | Hanya gejala yang dirasakan pengguna. Tanpa istilah teknis dan tanpa data alert. |
| Medium | Semi-teknis | Menyebut komponen dan gejala, ditambah sedikit data alert (nama alert). |
| Pro | Teknis lengkap | Data alert lengkap, dugaan penyebab, nama skill, langkah, batasan, dan cara verifikasi. |

## Contoh (TC-04, Postgres dan Redis mati)

Contoh ini hanya ilustrasi. Teks resmi ada di file template (lihat di bawah).

- **Noob:** "Toko online saya error, nggak bisa dipakai. Tolong benerin."
- **Medium:** "Ada alert PostgresDown dan RedisDown di server. Sepertinya database mati. Tolong cek dan pulihkan."
- **Pro:** "Alert PostgresDown (pg_up=0) dan RedisDown (redis_up=0) sejak 10:54:35. Container medusa-postgres dan medusa-redis Exited (137). Jalankan skill tc04-container-recovery: start kedua container, tunggu healthy, verifikasi pg_up=1 dan redis_up=1, jangan hapus volume."

## Penerapan

- **Template:** `alert-bridge/prompts/noob.txt`, `medium.txt`, dan `pro.txt`. Setiap file berisi teks untuk TC-01..TC-04, jadi totalnya 12 teks.
- **Pembuatan:** Claude membuat draf di awal Stage 9. Template level pro menyebut nama skill dan tool, yang baru ada di Stage 9. **Pengguna me-review** dulu sebelum template dipakai untuk benchmark.
- **Pemilihan level:** `PROMPT_LEVEL=noob|medium|pro` di `.env`. alert-bridge memilih template sesuai level dan skenario (`scenario` di label alert).
- **Pencatatan:** setiap alert yang diteruskan mencatat `prompt_level` di `benchmark/runs/alerts.jsonl`.
- **Benchmark (Stage 10):** satu batch per level. Set `PROMPT_LEVEL`, restart alert-bridge, lalu jalankan semua TC. Hasil metrik dikelompokkan per level dan per TC.

## Dampak ke benchmark

- **Jumlah run:** 3 level × 4 TC × 10 pengulangan (usulan) = **120 run per model**.
- **Perkiraan biaya Qwen:** $0,015–0,03 per run, jadi sekitar $2–4. Angka ini diukur ulang setelah Stage 9.

## Belum diputuskan

- **Skill di level noob:** apakah agent tetap boleh memakai skill bila menemukannya sendiri? Usulan: boleh, karena skill selalu terpasang dan yang diuji adalah kemampuan agent menghubungkan keluhan awam ke skill yang tepat. Menunggu konfirmasi dosen.
- **Jumlah pengulangan** per level per TC (usulan 10).

## Riwayat

| Tanggal | Perubahan |
|---|---|
| 2026-10-02 | Keputusan dosen tiga level dicatat. Draf template disepakati dibuat oleh Claude dan di-review pengguna. |
