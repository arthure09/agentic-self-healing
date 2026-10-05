"""Self-check alert-bridge tanpa jaringan: template per level dan penggabungan alert.
Jalankan: python3 alert-bridge/test_app.py"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.update(PROMPT_DIR=os.path.join(HERE, "..", "prompts"), ALERT_LOG_FILE=os.devnull)
spec = importlib.util.spec_from_file_location("app", os.path.join(HERE, "app.py"))
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

a = {"labels": {"alertname": "PostgresDown", "scenario": "tc04", "severity": "critical"},
     "annotations": {"summary": "PostgreSQL mati", "description": "x"},
     "startsAt": "2026-10-05T10:00:00Z", "fingerprint": "f1"}
b = {**a, "labels": {**a["labels"], "alertname": "RedisDown"}, "fingerprint": "f2"}

for lvl in ("noob", "medium", "pro"):
    app.PROMPT_LEVEL = lvl
    msg, path = app.build_message(a)
    assert path.endswith(f"{lvl}/tc04.txt") and "{" not in msg and "skenario" not in msg, (lvl, msg)
    assert ("PostgresDown" in msg) == (lvl != "noob"), lvl

assert app.claim_run(a, "tc04", 1000) is None              # alert pertama -> run baru
assert app.claim_run(b, "tc04", 2000) == "PostgresDown"    # alert susulan -> digabung
app.release(a, "tc04"); assert "tc04" in app._active
app.release(b, "tc04"); assert "tc04" not in app._active   # semua resolved -> bebas
assert app.claim_run(b, "tc04", 3000) is None              # gangguan baru -> run baru
assert app.claim_run(a, "tc04", 3000 + 301_000) is None    # lewat MERGE_WINDOW_S -> run baru
assert app.build_message({**a, "labels": {"alertname": "X"}})[1] == "-"  # tanpa template
print("OK")
