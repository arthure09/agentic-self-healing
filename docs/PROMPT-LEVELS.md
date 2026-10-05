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

- **Template:** folder `prompts/` dengan subfolder per level: `prompts/noob/`, `prompts/medium/`, `prompts/pro/`. Setiap subfolder berisi `tc01.txt`..`tc04.txt`, jadi totalnya 12 teks.
- **Placeholder:** diisi alert-bridge dari data alert. Medium memakai `{alertname}`. Pro memakai `{alertname}`, `{severity}`, `{starts_at}`, `{summary}`, dan `{description}`. Noob tidak memakai placeholder.
- **Pembuatan:** draf dibuat 2026-10-05 (Stage 9). Template level pro menyebut nama skill dan tool `container-status`. Tool lain disebut sebagai langkah, karena belum dibuat. Dipakai alert-bridge sejak 1.1.0 (2026-10-05).
- **System prompt (2026-10-05):** keputusan dosen, system prompt juga punya level. Baru versi pro: `prompts/system/pro.md`. Noob dan medium ditunda sampai keputusan dosen. Bagian "Laporan akhir" (`STATUS:`) adalah alat ukur, wajib di semua level, disimpan terpisah di `prompts/system/_report-format.md`. Belum dipasang ke workspace OpenClaw.
- **Pemeriksaan:** `python3 prompts/check_prompts.py` (kebocoran kata `chaos`, isi noob/medium sesuai definisi, placeholder, nama skill, format laporan).
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
| 2026-10-05 | Template pro ditulis ulang (nama tool asli, kriteria selesai yang bisa dicek tool, alasan setiap batasan). Noob TC-01 diganti (TC-01 tidak membuat toko down). System prompt pro + format laporan + skrip pemeriksaan ditambahkan. |
