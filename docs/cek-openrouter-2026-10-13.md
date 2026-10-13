# Cek OpenRouter: temperature dan kecepatan model (2026-10-13)

Pengecekan ini hanya membaca dan mengunduh data. Konfigurasi OpenClaw, alert-bridge, dan file benchmark tidak diubah. Data mentah ada di `benchmark/openrouter/`.

## 1. Dukungan parameter per penyedia

Sumber: `GET /api/v1/models/<model>/endpoints` (HTTP 200), disimpan di `benchmark/openrouter/endpoints-qwen3.7-plus.json` dan `endpoints-gemini-3.8-flash.json`.

| Model | Penyedia (tag) | Kuantisasi | temperature | reasoning |
|---|---|---|---|---|
| qwen/qwen3.7-plus | Alibaba (`alibaba/us-east-1`) | unknown | ya | ya |
| qwen/qwen3.7-plus | Alibaba (`alibaba`) | unknown | ya | ya |
| google/gemini-3.8-flash | Google AI Studio (`google-ai-studio/flex`) | unknown | ya | ya |
| google/gemini-3.8-flash | Google AI Studio (`google-ai-studio`) | unknown | ya | ya |
| google/gemini-3.8-flash | Google AI Studio (`google-ai-studio/priority`) | unknown | ya | ya |
| google/gemini-3.8-flash | Google Vertex (`google-vertex/global/flex`) | unknown | **tidak** | ya |
| google/gemini-3.8-flash | Google Vertex (`google-vertex/global`) | unknown | **tidak** | ya |
| google/gemini-3.8-flash | Google Vertex (`google-vertex/global/priority`) | unknown | **tidak** | ya |

Qwen hanya punya penyedia Alibaba. Untuk Gemini, endpoint Google Vertex tidak mencantumkan `temperature`.

## 2. Unduhan data generation

Sumber: `GET /api/v1/generation?id=<gen-...>`, satu baris per ID, ditambah `run_id`, `key`, `level`, `tc`, `session_id`, `turn`. Jeda 0,2 s, percobaan ulang hanya untuk 429/5xx (tidak terpakai).

| Batch | ID berhasil / total | Gagal | File |
|---|---|---|---|
| qwen-full-1 | 661 / 661 | 0 | `benchmark/openrouter/generation-qwen-full-1.jsonl` |
| qwen-uji-2 | 74 / 74 | 0 | `benchmark/openrouter/generation-qwen-uji-2.jsonl` |

## 3. Ringkasan (dihitung dari file)

### Penyedia

| Batch | Penyedia | Model | Panggilan dengan 429 lalu diulang OpenRouter |
|---|---|---|---|
| qwen-full-1 | Alibaba 661/661 | `qwen/qwen3.7-plus-20260602` 661/661 | 6 (ke Alibaba lagi, lalu 200) |
| qwen-uji-2 | Alibaba 74/74 | `qwen/qwen3.7-plus-20260602` 74/74 | 1 (ke Alibaba lagi, lalu 200) |

Qwen **selalu dilayani Alibaba**, versi model sama. Ada dua `endpoint_id` Alibaba: qwen-full-1 638 + 23 panggilan, qwen-uji-2 71 + 3. Respons endpoints tidak memuat `endpoint_id`, jadi tidak bisa dipastikan mana yang `alibaba/us-east-1` dan mana yang `alibaba`. Semua panggilan memakai streaming, tidak ada yang dibatalkan. Hasil akhir panggilan: `tool_calls` 541 + `stop` 120 (qwen-full-1), `tool_calls` 62 + `stop` 12 (qwen-uji-2).

### Token per detik per panggilan = `tokens_completion` ÷ (`generation_time` / 1000)

Semua panggilan: qwen-full-1 **32,1 (15,1–54,6)**, n = 661; qwen-uji-2 **33,1 (13,0–50,9)**, n = 74. Median (min–maks):

| TC | Level | qwen-full-1 (n) | qwen-full-1 token/detik | qwen-uji-2 (n) | qwen-uji-2 token/detik |
|---|---|---|---|---|---|
| tc01 | noob | 65 | 31,4 (16,7–45,1) | 6 | 34,4 (19,6–43,2) |
| tc01 | medium | 58 | 33,2 (19,2–42,1) | 7 | 36,0 (22,0–43,4) |
| tc01 | pro | 65 | 30,5 (15,2–48,5) | 5 | 30,8 (23,9–41,3) |
| tc02 | noob | 59 | 41,6 (18,7–54,3) | 10 | 36,2 (13,0–50,8) |
| tc02 | medium | 45 | 41,1 (17,6–54,6) | 3 | 38,7 (38,5–49,5) |
| tc02 | pro | 28 | 39,7 (21,0–51,0) | 4 | 45,9 (33,0–50,9) |
| tc03 | noob | 50 | 28,7 (20,0–41,1) | 5 | 33,4 (19,3–36,0) |
| tc03 | medium | 42 | 31,4 (16,5–39,7) | 5 | 33,8 (31,3–35,3) |
| tc03 | pro | 48 | 31,9 (16,4–47,6) | 4 | 29,2 (22,4–33,2) |
| tc04 | noob | 76 | 30,0 (15,2–53,1) | 13 | 27,8 (16,6–43,1) |
| tc04 | medium | 70 | 31,4 (15,1–46,6) | 6 | 34,9 (16,9–42,3) |
| tc04 | pro | 55 | 31,3 (15,1–50,5) | 6 | 27,4 (14,7–42,2) |

n = jumlah panggilan model, bukan jumlah run.

Catatan: `tokens_completion` (hitungan OpenRouter) hampir selalu berbeda dari `native_tokens_completion` (hitungan penyedia): 660/661 berbeda. Contoh: 105 vs 100.

### Arti `latency` dan `generation_time`

Dokumentasi OpenRouter ([Get a generation](https://openrouter.ai/docs/api/api-reference/generations/get-generation)): `latency` = "Total latency in milliseconds", `generation_time` = "Time taken for generation in milliseconds".

**Data tidak cocok dengan arti "total".** Perbandingan dengan lama setiap giliran yang dicatat OpenClaw (waktu kirim permintaan → respons selesai, dicocokkan lewat `responseId`):

| | qwen-full-1 (661) | qwen-uji-2 (74) |
|---|---|---|
| `latency` (ms) | 1.366 (667–3.549) | 1.418 (726–2.434) |
| `generation_time` (ms) | 4.523 (1.945–30.010) | 4.578 (2.218–12.717) |
| Lama giliran OpenClaw (ms) | 4.804 (2.207–30.404) | 4.908 (2.352–12.911) |
| `latency` < `generation_time` | 661/661 | 74/74 |
| OpenClaw − `generation_time` (ms) | 208 (97–2.474), selalu ≥ 0 | 186 (100–1.293), selalu ≥ 0 |
| OpenClaw − (`latency` + `generation_time`) (ms) | −1.107 (−2.189 sampai 1.180) | −1.178 (−2.276 sampai −17) |

Contoh (qwen-full-1): latency 1.508 / generation_time 4.616 / OpenClaw 5.516 ms; latency 1.142 / 3.261 / 3.395; latency 1.699 / 5.879 / 6.015.

Artinya:
- `generation_time` hampir sama dengan seluruh durasi panggilan. Lebih pendek dari giliran OpenClaw hanya ±0,2 s.
- `latency` selalu lebih kecil, dan latency + generation_time melebihi durasi nyata. Jadi `latency` adalah **bagian di dalam** `generation_time`, bukan total. Pola ini cocok dengan waktu sampai token pertama (TTFT). Tetapi tanpa proxy pencatat, ini belum bisa dibuktikan langsung.
- Akibatnya, rumus token/detik di atas ikut menghitung waktu tunggu token pertama. Sebagai pembanding saja: `tokens_completion` ÷ (`generation_time` − `latency`) = 46,4 (31,2–95,3) untuk qwen-full-1 dan 47,6 (26,3–63,0) untuk qwen-uji-2. Angka ini mendekati `throughput_last_30m` p50 = 50 token/detik di respons endpoints Alibaba.

### Temperature di data generation

**Tidak ada** field yang menunjukkan temperature atau parameter sampling yang dipakai penyedia, baik di respons maupun di daftar field dokumentasi.

## 4. Nilai temperature yang disarankan

| Model | Temuan | Sumber |
|---|---|---|
| Qwen3.7 Plus, halaman model OpenRouter | Tidak ditemukan (hanya "temperature: optional") | [openrouter.ai/qwen/qwen3.7-plus](https://openrouter.ai/qwen/qwen3.7-plus) |
| Qwen3.7 Plus, dokumentasi API Alibaba (Model Studio) | Tidak ditemukan untuk qwen3.7-plus. Rentang [0, 2), atur temperature **atau** top_p saja. Bawaan per mode hanya disebut untuk Qwen3.8-Omni-Flash (thinking 0,6, non-thinking 0,7) | [OpenAI compatible – Chat](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions) |
| Qwen3.7 Plus, blog resmi rilis | Bukan saran pemakaian. Pengaturan **evaluasi benchmark**: "temp=1.0, top_p=0.95, top_k=20" (Terminal-Bench 2.0) dan "temp=1.0, top_p=0.95" (SWE-Bench) | [Alibaba Cloud blog: Qwen3.7-Plus](https://www.alibabacloud.com/blog/qwen3-7-plus-multimodal-agent-intelligence_603206) |
| Qwen3.7 Plus, mode thinking | Thinking aktif secara bawaan (model hybrid) | [Deep thinking (Model Studio)](https://www.alibabacloud.com/help/en/model-studio/deep-thinking) |
| Gemini 3.8 Flash, halaman model OpenRouter | Tidak ditemukan (hanya "temperature: optional") | [openrouter.ai/google/gemini-3.8-flash](https://openrouter.ai/google/gemini-3.8-flash) |
| Gemini 3.8 Flash, panduan Google Cloud | "Deprecated sampling parameters (`temperature`, `top_k`, `top_p`): These parameters are ignored by the backend." Determinisme diatur lewat `thinking_level` | [Developer's guide to Gemini 3.8 Flash](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/guides/gemini-3-8-flash) |
| Gemini 3.8 Flash, halaman model Google Cloud | Nilai bawaan: Temperature 1.0, topP 0.95, topK 64 | [Gemini 3.8 Flash](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-flash) |
| Gemini 3, panduan Gemini API | "we strongly recommend keeping the temperature parameter at its default value of `1.0`". Halaman ini ditandai deprecated | [Gemini 3 developer guide](https://ai.google.dev/gemini-api/docs/gemini-3) |

Untuk Qwen3.7 Plus tidak ditemukan nilai temperature yang disarankan secara resmi. Satu-satunya angka resmi (1,0) adalah pengaturan evaluasi benchmark. Untuk Gemini 3.8 Flash, Google menyebut temperature diabaikan backend, dengan bawaan 1,0.

## Catatan

- `benchmark/openrouter/` belum di-commit dan tidak masuk `.gitignore`. File memuat `app_id`, `workspace_id`, dan `request_id` akun OpenRouter, tetapi tidak memuat API key (sudah dicek).
- Skrip unduh dan ringkasan sementara ada di scratchpad sesi, bukan di repo.
