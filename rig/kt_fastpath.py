"""
kt_fastpath.py -- fine-grained forward path sampler (the 30s gap closer).

Why this exists: kt_sweep.py showed every come TP/stop rule loses. But its forward samples
start at h=30s, so a pop that happens in the first few seconds and decays is INVISIBLE.
This samples every FAST_TICK seconds for FAST_DURATION seconds after each new signal, so
that question can actually be answered.

Runs alongside the kill test. Read-only w.r.t. the rig's own files: it only appends to
logs/fastpath.jsonl. It tails signals.jsonl from the current end, so it only samples signals
detected AFTER launch.

  python kt_fastpath.py            # run forever (Ctrl-C to stop)
  python kt_fastpath.py 60 180     # tick=60s? no -- args are: TICK DURATION
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, r"C:\killtest-rig")
from kt_lib import Store, Prices, load_config       # noqa: E402

FAST_TICK = 3.0        # seconds between samples
FAST_DURATION = 120.0  # how long to follow each signal
MAX_ACTIVE = 120       # safety cap


def main(argv: list[str]) -> int:
    tick = float(argv[1]) if len(argv) > 1 else FAST_TICK
    duration = float(argv[2]) if len(argv) > 2 else FAST_DURATION

    cfg = load_config()
    store = Store(os.path.join(r"C:\killtest-rig", cfg.get("log_dir", "logs")))
    prices = Prices(store)
    sigfile = os.path.join(store.dir, "signals.jsonl")
    outfile = os.path.join(store.dir, "fastpath.jsonl")

    # start at the END of the signal file: only sample signals seen from now on
    offset = os.path.getsize(sigfile) if os.path.exists(sigfile) else 0
    active: list[dict] = []
    n_sig = n_samp = n_miss = 0

    print(f"fastpath sampler: tick={tick:.1f}s duration={duration:.0f}s")
    print(f"  tailing {sigfile} from byte {offset}")
    print(f"  writing {outfile}", flush=True)

    try:
        while True:
            now = time.time()

            # ---- ingest newly appended signals (incremental, no full re-read) ----
            try:
                size = os.path.getsize(sigfile)
                if size < offset:            # file was rotated/truncated
                    offset = 0
                if size > offset:
                    with open(sigfile, "r", encoding="utf-8", errors="ignore") as f:
                        f.seek(offset)
                        for line in f:
                            if not line.endswith("\n"):   # partial write; retry next pass
                                break
                            offset += len(line.encode("utf-8", "ignore"))
                            try:
                                r = json.loads(line)
                            except Exception:
                                continue
                            if r.get("kind") != "signal":
                                continue
                            if not r.get("usable") or not r.get("entry_price"):
                                continue
                            if len(active) >= MAX_ACTIVE:
                                continue
                            active.append({
                                "id": r.get("id"), "mint": r.get("mint"),
                                "wallet": r.get("wallet"), "entry": r.get("entry_price"),
                                "config_fp": r.get("config_fp"),
                                "lat": r.get("latency_sec_slot"),
                                "start": now, "next": now, "done": 0,
                            })
                            n_sig += 1
            except Exception as e:
                print(f"  ingest error: {type(e).__name__}: {e}", flush=True)

            # ---- sample every active path whose next tick is due ----
            still = []
            for p in active:
                while p["next"] <= now and (p["next"] - p["start"]) <= duration:
                    t = p["next"] - p["start"]
                    price = None
                    try:
                        # ttl=0 bypasses the 10s cache -- essential for 3s resolution
                        price = prices.price_fast(p["mint"], ttl=0.0)
                    except Exception:
                        pass
                    if price:
                        ret = (price / p["entry"] - 1.0) * 100.0
                        store._append(outfile, {
                            "kind": "fp", "id": p["id"], "mint": p["mint"],
                            "wallet": p["wallet"], "config_fp": p["config_fp"],
                            "latency_sec_slot": p["lat"],
                            "entry": p["entry"], "t_sec": round(t, 2),
                            "price": price, "ret_pct": round(ret, 4),
                            "ts": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
                        })
                        n_samp += 1
                        p["done"] += 1
                    else:
                        n_miss += 1
                    p["next"] += tick
                if (p["next"] - p["start"]) <= duration:
                    still.append(p)
            active = still

            if n_sig and n_sig % 5 == 0 and n_samp % 25 < 3:
                print(f"  signals={n_sig} samples={n_samp} missed={n_miss} active={len(active)}",
                      flush=True)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print(f"\nstopped. signals={n_sig} samples={n_samp} missed={n_miss}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
