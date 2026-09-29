#!/usr/bin/env python3
"""TC-01 — connection pool exhaustion.

Membuka 45 koneksi simultan ke PostgreSQL (max_connections=50) lalu menahannya
dalam keadaan idle sampai --hold detik habis, SIGTERM/SIGINT diterima, atau
koneksi diputus dari sisi server (mis. agent memanggil pg_terminate_backend).

Semua koneksi memakai application_name=chaos_tc01 agar mudah diidentifikasi.
Koneksi yang ditolak karena slot habis ("too many clients") dicatat sebagai
bagian dari hasil, bukan error script.
"""
import argparse
import signal
import threading
import time

import psycopg

from common import load_env, log_event, new_run_id, pg_dsn, write_pidfile

SCENARIO = "tc01"
APP_NAME = "chaos_tc01"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--connections", type=int, default=45)
    parser.add_argument("--hold", type=int, default=600, help="detik menahan koneksi")
    args = parser.parse_args()

    env = load_env()
    run_id = new_run_id(SCENARIO)
    pidfile = write_pidfile(SCENARIO)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    dsn = pg_dsn(env, APP_NAME)
    conns, errors, lock = [], [], threading.Lock()

    def open_one():
        try:
            c = psycopg.connect(dsn, autocommit=True)
            with lock:
                conns.append(c)
        except psycopg.OperationalError as e:
            with lock:
                errors.append(str(e).strip().splitlines()[-1])

    log_event(run_id, SCENARIO, "inject_start",
              params={"connections": args.connections, "hold_s": args.hold})
    threads = [threading.Thread(target=open_one) for _ in range(args.connections)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    log_event(run_id, SCENARIO, "inject_done",
              opened=len(conns), refused=len(errors),
              refused_reasons=sorted(set(errors)))

    # Tahan koneksi; berhenti lebih awal bila semua koneksi diputus server.
    deadline = time.monotonic() + args.hold
    reason = "hold_elapsed"
    while time.monotonic() < deadline:
        if stop.wait(2):
            reason = "signal"
            break
        alive = 0
        for c in conns:
            try:
                c.execute("SELECT 1")
                alive += 1
            except psycopg.Error:
                pass
        if conns and alive == 0:
            reason = "terminated_by_server"
            break

    alive_at_end = 0
    for c in conns:
        if not c.closed and not c.broken:
            alive_at_end += 1
        c.close()
    log_event(run_id, SCENARIO, "inject_end", reason=reason,
              still_open_at_end=alive_at_end)
    pidfile.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
