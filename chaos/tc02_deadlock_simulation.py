#!/usr/bin/env python3
"""TC-02 — deadlock (circular dependency).

Dua transaksi paralel mengunci dua baris yang sama dengan urutan terbalik:
  T1: lock baris 1 -> tunggu -> lock baris 2
  T2: lock baris 2 -> tunggu -> lock baris 1
PostgreSQL mendeteksi siklus setelah deadlock_timeout (1 s), membatalkan salah
satu transaksi, dan menaikkan counter pg_stat_database.deadlocks.

Tabel uji ada di skema terpisah (nama dari chaos/names.json) agar tidak
menyentuh tabel Medusa.
"""
import argparse
import threading
import time

import psycopg

from common import NAMES, load_env, log_event, new_run_id, pg_dsn

SCENARIO = "tc02"
APP_NAME = NAMES["tc02"]["application_name"]
SCHEMA = NAMES["tc02"]["schema"]
TABLE = f'{SCHEMA}.{NAMES["tc02"]["table"]}'
SETUP_SQL = f"""
CREATE SCHEMA IF NOT EXISTS {SCHEMA};
CREATE TABLE IF NOT EXISTS {TABLE} (id int PRIMARY KEY, balance int NOT NULL);
INSERT INTO {TABLE} VALUES (1, 1000), (2, 1000)
  ON CONFLICT (id) DO UPDATE SET balance = EXCLUDED.balance;
"""


def deadlock_count(conn) -> int:
    return conn.execute(
        "SELECT deadlocks FROM pg_stat_database WHERE datname = current_database()"
    ).fetchone()[0]


def one_round(dsn: str) -> dict:
    barrier = threading.Barrier(2)
    outcome = {}

    def tx(name, first, second):
        with psycopg.connect(dsn) as c:
            try:
                c.execute(f"UPDATE {TABLE} SET balance = balance - 1 WHERE id = %s", (first,))
                barrier.wait(timeout=10)
                c.execute(f"UPDATE {TABLE} SET balance = balance + 1 WHERE id = %s", (second,))
                c.commit()
                outcome[name] = "committed"
            except psycopg.errors.DeadlockDetected:
                c.rollback()
                outcome[name] = "deadlock_victim"

    threads = [
        threading.Thread(target=tx, args=("T1", 1, 2)),
        threading.Thread(target=tx, args=("T2", 2, 1)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--rounds", type=int, default=3, help="jumlah deadlock yang dipicu")
    parser.add_argument("--interval", type=float, default=2.0, help="jeda antar-round (detik)")
    args = parser.parse_args()

    env = load_env()
    run_id = new_run_id(SCENARIO)
    dsn = pg_dsn(env, APP_NAME)

    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(SETUP_SQL)
        before = deadlock_count(admin)

    log_event(run_id, SCENARIO, "inject_start",
              params={"rounds": args.rounds, "interval_s": args.interval},
              deadlocks_before=before)
    results = []
    for i in range(args.rounds):
        results.append(one_round(dsn))
        if i < args.rounds - 1:
            time.sleep(args.interval)

    # pg_stat_database diperbarui secara asinkron; beri jeda singkat.
    time.sleep(1)
    with psycopg.connect(dsn, autocommit=True) as admin:
        after = deadlock_count(admin)
    log_event(run_id, SCENARIO, "inject_done", rounds=results,
              deadlocks_before=before, deadlocks_after=after,
              deadlocks_added=after - before)


if __name__ == "__main__":
    main()
