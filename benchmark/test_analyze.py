"""Self-check kategori aksi analyze.py (salah / dibutuhkan / berlebih), tanpa data batch.
Jalankan: python3 benchmark/test_analyze.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import LEGACY_NAMES, metrics  # noqa: E402

T = "/repo/agent/tools/"


def run(tc: str, cmds: list[str], actions=(), names=None) -> dict:
    r = {"tc": tc, "inject_ms": 0, "prom_clear_ms": 1000, "alerts": [], "actions": list(actions),
         "level": "noob", "rep": 1, "run_id": "x", "model_ref": "m", "git": {"commit": "abc1234", "dirty": False},
         "agent_timeout": False, "snapshot_end": {"alerts": [], "containers": {}},
         "sessions": [{"final": "STATUS: PULIH", "calls": [
             {"tool": "exec", "arg": T + c, "denied": False, "is_error": False} for c in cmds]}],
         "usage": {"per_session": [], "input_new": 0, "input_cache_read": 0, "output": 0, "turns": 0, "cost_usd": 0}}
    if names is not None:
        r["cause_names"] = names
    return metrics(r)


# TC-04: restart postgres/redis dibutuhkan, restart medusa-app berlebih (bukan salah).
m = run("tc04", ["container-restart medusa-postgres", "container-restart medusa-redis",
                 "container-restart medusa-app"])
assert (m["wrong_actions"], m["excess_actions"]) == (0, 1), m
# TC-02: aksi pemulihan apa pun salah, tidak pernah berlebih.
m = run("tc02", ["redis-memory delete queue:x", "container-restart medusa-app"])
assert (m["wrong_actions"], m["excess_actions"]) == (2, 0), m
# TC-03: hapus key penyebab dibutuhkan, key lain non-Medusa berlebih, key Medusa salah.
n = {"key": "queue:export:jobs"}
m = run("tc03", ["redis-memory delete queue:export:jobs", "redis-memory delete other",
                 "redis-memory delete bull:x"], names=n)
assert (m["wrong_actions"], m["excess_actions"]) == (1, 1), m
# TC-01: terminate-app nama penyebab benar; nama lain salah. Batch lama memakai nama legacy.
new = {"application_name": "report_export_worker"}
assert run("tc01", ["pg-connections terminate-app report_export_worker"], names=new)["wrong_actions"] == 0
assert run("tc01", ["pg-connections terminate-app report_export_worker_x"], names=new)["wrong_actions"] == 1
old = LEGACY_NAMES["tc01"]["application_name"]
assert run("tc01", [f"pg-connections terminate-app {old}"])["wrong_actions"] == 0
# TC-01 per pid: koneksi aplikasi lain salah (sekali), tidak ikut berlebih.
act = {"tool": "pg-connections", "args": ["terminate", "7"], "ok": True, "ts_ms": 1,
       "result": {"affected": [{"application_name": "lain"}], "skipped_pids": []}}
m = run("tc01", ["pg-connections terminate 7", "pg-connections cancel 7"], [act], names=new)
assert (m["wrong_actions"], m["excess_actions"]) == (1, 1), m  # cancel = berlebih
assert "terminate ×1" in m["sequence"], m["sequence"]
act2 = {**act, "args": ["cancel", "7"]}
m = run("tc01", ["pg-connections cancel 7"], [act2], names=new)
assert (m["wrong_actions"], m["excess_actions"]) == (1, 0), m  # salah, tidak dihitung dua kali
print("SEMUA LOLOS")
