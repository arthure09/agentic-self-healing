#!/usr/bin/env python3
"""TC-03 — Redis memory flooding.

Memasukkan 10.000 task palsu ke antrean Redis (list `queue:chaos:tasks`)
sampai pemakaian memori melewati 85% dari maxmemory (256 MB).

Ukuran payload default 24 KiB: 10.000 x 24 KiB ~ 234 MiB ~ 91% dari 256 MiB,
cukup untuk melewati ambang 85% tanpa langsung menabrak batas. Redis memakai
maxmemory-policy noeviction, sehingga bila batas tercapai write ditolak
(OOM) alih-alih meng-evict key milik Medusa; script berhenti dengan rapi
bila itu terjadi.
"""
import argparse
import json
import os
import uuid

import redis

from common import log_event, new_run_id, now_ms, redis_url

SCENARIO = "tc03"
QUEUE_KEY = "queue:chaos:tasks"


def memory_pct(r) -> tuple[int, int, float]:
    info = r.info("memory")
    used, maxmem = info["used_memory"], info["maxmemory"]
    return used, maxmem, round(used * 100 / maxmem, 2) if maxmem else 0.0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--count", type=int, default=10_000)
    parser.add_argument("--payload-kb", type=int, default=24)
    parser.add_argument("--batch", type=int, default=200)
    args = parser.parse_args()

    r = redis.Redis.from_url(redis_url())
    run_id = new_run_id(SCENARIO)
    # Satu blok acak dipakai ulang: isi payload tidak memengaruhi memori Redis.
    filler = os.urandom(args.payload_kb * 1024 // 2).hex()

    used, maxmem, pct = memory_pct(r)
    log_event(run_id, SCENARIO, "inject_start",
              params={"count": args.count, "payload_kb": args.payload_kb, "key": QUEUE_KEY},
              used_memory=used, maxmemory=maxmem, used_pct=pct)

    pushed, oom = 0, None
    try:
        while pushed < args.count:
            pipe = r.pipeline(transaction=False)
            n = min(args.batch, args.count - pushed)
            for i in range(n):
                pipe.lpush(QUEUE_KEY, json.dumps({
                    "id": str(uuid.uuid4()),
                    "type": "chaos.fake_task",
                    "seq": pushed + i,
                    "created_ms": now_ms(),
                    "payload": filler,
                }))
            pipe.execute()
            pushed += n
    except redis.exceptions.ResponseError as e:
        if "OOM" not in str(e):
            raise
        oom = str(e)
        pushed = r.llen(QUEUE_KEY)

    used, maxmem, pct = memory_pct(r)
    log_event(run_id, SCENARIO, "inject_done", tasks_in_queue=r.llen(QUEUE_KEY),
              pushed=pushed, oom_error=oom, used_memory=used, maxmemory=maxmem,
              used_pct=pct)


if __name__ == "__main__":
    main()
