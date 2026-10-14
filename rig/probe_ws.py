"""
probe_ws.py -- find a FREE websocket endpoint that actually DELIVERS notifications.

Context: Alchemy connected and subscribed without error but pushed zero notifications
(ws_notifs=0), which left detection to the 60s poll. This script tests candidate public
websocket endpoints by subscribing to real, active wallets and counting what arrives.

  python probe_ws.py             # test all candidates, ~40s each
  python probe_ws.py 60          # longer listen window

No keys, no writes to the kill test logs, read-only probing.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

sys.path.insert(0, r"C:\killtest-rig")

# Free / no-key public Solana websocket endpoints
CANDIDATES = [
    ("publicnode",   "wss://solana-rpc.publicnode.com"),
    ("drpc",         "wss://solana.drpc.org"),
    ("official",     "wss://api.mainnet-beta.solana.com"),
    ("official-alt", "wss://api.mainnet.solana.com"),
    ("1rpc",         "wss://1rpc.io/solana"),
    ("ankr",         "wss://rpc.ankr.com/solana/ws"),
]

WALLETS = [
    "3K7XMbqvFTKT211Dqu8tXC1iK5vmQQ2MZp5mxSdEzWvx",
    "F6pq4UnxJVGfNiFdW9YJG1QPppvNuCdFWTNqdWqpeiCZ",
    "8zkgFGVZrDLieViwqiXFCydSX6WL5hsxmUu55yBdsNsZ",
]


async def test_endpoint(name: str, url: str, listen: float) -> dict:
    import websockets
    res = {"name": name, "url": url, "connected": False, "subs_ok": 0, "subs_err": 0,
           "logs_notifs": 0, "acct_notifs": 0, "error": None, "first_seen_s": None}
    try:
        t0 = time.time()
        async with websockets.connect(url, ping_interval=20, open_timeout=15,
                                      close_timeout=5, max_size=2 ** 22) as ws:
            res["connected"] = True
            ids = {}
            nid = 1
            # logsSubscribe with mentions, one per wallet (how the rig works today)
            for w in WALLETS:
                ids[nid] = ("logs", w)
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": nid, "method": "logsSubscribe",
                                          "params": [{"mentions": [w]},
                                                     {"commitment": "confirmed"}]}))
                nid += 1
            # accountSubscribe on the wallet itself: far fewer events, widely supported
            for w in WALLETS[:2]:
                ids[nid] = ("acct", w)
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": nid, "method": "accountSubscribe",
                                          "params": [w, {"commitment": "confirmed",
                                                         "encoding": "base64"}]}))
                nid += 1

            deadline = time.time() + listen
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(1.0, deadline - time.time()))
                except asyncio.TimeoutError:
                    break
                try:
                    d = json.loads(raw)
                except Exception:
                    continue
                if "id" in d and ("result" in d or "error" in d):
                    if d.get("error"):
                        res["subs_err"] += 1
                    else:
                        res["subs_ok"] += 1
                    continue
                m = d.get("method")
                if m == "logsNotification":
                    res["logs_notifs"] += 1
                    if res["first_seen_s"] is None:
                        res["first_seen_s"] = round(time.time() - t0, 1)
                elif m == "accountNotification":
                    res["acct_notifs"] += 1
                    if res["first_seen_s"] is None:
                        res["first_seen_s"] = round(time.time() - t0, 1)
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {str(e)[:70]}"
    return res


async def main() -> int:
    listen = float(sys.argv[1]) if len(sys.argv) > 1 else 40.0
    print("=" * 92)
    print(f"WEBSOCKET DELIVERY PROBE -- {listen:.0f}s per endpoint, {len(WALLETS)} wallets")
    print("=" * 92)
    results = []
    for name, url in CANDIDATES:
        print(f"\n--- {name}  ({url})")
        r = await test_endpoint(name, url, listen)
        results.append(r)
        if not r["connected"]:
            print(f"    CONNECT FAILED: {r['error']}")
            continue
        print(f"    connected; subscribed ok={r['subs_ok']} err={r['subs_err']}")
        print(f"    logsNotification={r['logs_notifs']}  accountNotification={r['acct_notifs']}"
              f"  first@{r['first_seen_s']}s")
        if r["logs_notifs"] or r["acct_notifs"]:
            print("    >>> DELIVERS NOTIFICATIONS")
        else:
            print("    >>> connected but SILENT (like Alchemy)")

    print("\n" + "=" * 92)
    print("SUMMARY -- endpoints that actually deliver")
    print("=" * 92)
    good = [r for r in results if r["logs_notifs"] or r["acct_notifs"]]
    if good:
        for r in sorted(good, key=lambda x: -(x["logs_notifs"] + x["acct_notifs"])):
            print(f"  {r['name']:<14} logs={r['logs_notifs']:<4} acct={r['acct_notifs']:<4} {r['url']}")
    else:
        print("  NONE delivered. Free public websockets are not usable for logsSubscribe here.")
        print("  -> fall back to a faster poll, or pay for a ws-capable provider.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
