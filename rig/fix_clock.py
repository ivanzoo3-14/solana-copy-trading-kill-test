"""
fix_clock.py -- correct the local system clock using Solana block time as the reference.

Why: this machine cannot reach any NTP server (UDP 123 is blocked outbound to both
time.windows.com and time.google.com), and the Windows Time service was Disabled, so the
clock free-ran ~52s slow. Solana blocks carry a cluster timestamp accurate to ~1s, so the
chain makes a perfectly good time reference when NTP is unreachable.

  python fix_clock.py            # measure only (safe, no changes, no admin needed)
  python fix_clock.py --set      # measure AND correct (REQUIRES an elevated/Admin shell)

Run from an Administrator prompt for --set. Without it, use the printed PowerShell line.
"""
from __future__ import annotations

import statistics
import subprocess
import sys
import time
import os

sys.path.insert(0, r"C:\killtest-rig")
from kt_lib import Store, Rpc, load_config, load_rpc_credentials   # noqa: E402

SAMPLES = 7
DEADBAND_SEC = 1.5


def measure(rpc: Rpc) -> float | None:
    offs: list[float] = []
    for _ in range(SAMPLES):
        slot = rpc.call("getSlot", [{"commitment": "confirmed"}])
        if not slot:
            continue
        # use a slightly older slot: the newest block times can be unavailable.
        # Its blockTime is OLDER than now by (slot-ref) slots, so add that age back --
        # without this the result is biased ~-13s and wrongly reports a fast clock.
        ref = int(slot) - 32
        bt = rpc.call("getBlockTime", [ref])
        if bt:
            age_sec = max(0, int(slot) - ref) * 0.4
            offs.append((float(bt) + age_sec) - time.time())
        time.sleep(0.35)
    if not offs:
        return None
    offs.sort()
    core = offs[1:-1] if len(offs) > 3 else offs
    print(f"  samples: {[round(o, 2) for o in offs]}")
    return statistics.median(core)


def main(argv: list[str]) -> int:
    cfg = load_config()
    store = Store(os.path.join(r"C:\killtest-rig", cfg.get("log_dir", "logs")))
    creds = load_rpc_credentials(cfg.get("legion_config_path"))
    rpc = Rpc(creds["rpc_urls"] + [cfg["fallback_rpc_url"]], store, 40000)
    rpc.pick_healthy(probe_sig=None)

    print("=" * 74)
    print("CLOCK CORRECTION via Solana block time (NTP is unreachable on this machine)")
    print("=" * 74)
    skew = measure(rpc)
    if skew is None:
        print("could not measure chain time - check RPC connectivity")
        return 1

    print(f"\n  skew (chain - local) = {skew:+.2f} s")
    if abs(skew) < DEADBAND_SEC:
        print("  clock is already within tolerance; nothing to do.")
        return 0
    direction = "BEHIND" if skew > 0 else "AHEAD"
    print(f"  your clock is {abs(skew):.1f}s {direction} of true time")
    # to fix: local must move BY +skew seconds (add if behind, subtract if ahead)
    delta = round(skew, 1)
    ps_line = f'Set-Date -Date (Get-Date).AddSeconds({delta})'
    print(f"\n  correction: move the clock {delta:+.1f}s")
    print(f"    PowerShell (needs Admin):  {ps_line}")

    if "--set" not in argv:
        print("\n  (measure-only run. Re-run with --set from an ADMIN shell to apply.)")
        return 0

    print("\n  applying...")
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-Command", ps_line],
                           capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            print(f"  FAILED (rc={p.returncode}): {(p.stderr or p.stdout).strip()[:300]}")
            print("  -> this must be run from an ELEVATED (Administrator) shell.")
            return 1
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        print("  -> apply the PowerShell line above by hand in an Admin window.")
        return 1

    time.sleep(2)
    print("  re-measuring to verify...")
    after = measure(rpc)
    if after is None:
        print("  could not verify")
        return 1
    print(f"\n  skew after correction = {after:+.2f} s")
    if abs(after) < DEADBAND_SEC:
        print("  SUCCESS - clock is now in sync (within tolerance).")
    else:
        print(f"  partially corrected. Re-run --set to converge (remaining {after:+.1f}s).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
