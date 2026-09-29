#!/usr/bin/env python3
"""TC-04 — container down.

Menghentikan paksa (SIGKILL lewat `docker kill`) container PostgreSQL dan Redis,
lalu mencatat status tiap container setelahnya, termasuk apakah Docker
menghidupkannya kembali sendiri lewat restart policy.
"""
import argparse
import subprocess
import time

from common import log_event, new_run_id

SCENARIO = "tc04"
DEFAULT_TARGETS = ["medusa-postgres", "medusa-redis"]


def state(name: str) -> dict:
    out = subprocess.run(
        ["docker", "inspect", "-f",
         "{{.State.Status}} {{.State.ExitCode}} {{.RestartCount}} {{.HostConfig.RestartPolicy.Name}}",
         name],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    return {"status": out[0], "exit_code": int(out[1]),
            "restart_count": int(out[2]), "restart_policy": out[3]}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--targets", nargs="+", default=DEFAULT_TARGETS)
    parser.add_argument("--observe", type=float, default=10.0,
                        help="detik mengamati status setelah kill")
    args = parser.parse_args()

    run_id = new_run_id(SCENARIO)
    log_event(run_id, SCENARIO, "inject_start", params={"targets": args.targets},
              before={t: state(t) for t in args.targets})
    killed = subprocess.run(["docker", "kill", *args.targets],
                            capture_output=True, text=True)
    log_event(run_id, SCENARIO, "inject_done", returncode=killed.returncode,
              stderr=killed.stderr.strip() or None)

    time.sleep(args.observe)
    after = {t: state(t) for t in args.targets}
    log_event(run_id, SCENARIO, "observe", after_s=args.observe, after=after,
              auto_restarted=[t for t, s in after.items() if s["status"] == "running"])


if __name__ == "__main__":
    main()
