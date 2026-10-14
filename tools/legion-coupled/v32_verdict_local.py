"""v32_verdict_local.py -- run kt_wallets' registered verdict code path with zero LEGION access.

kt_wallets.main() calls load_config(), which opens LEGION\\config.json to read the allowlisted
RPC-key fields. The verdict itself is pure file analysis over killtest/logs/signals.jsonl. This
wrapper substitutes the rig's OWN config.json (parsed directly, no key material in it) so the
authoritative code path runs unchanged and no LEGION file is opened at all.

  python v32_verdict_local.py
  python v32_verdict_local.py --explore
"""
import json
import sys

sys.path.insert(0, r"C:\killtest-rig")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import kt_wallets as kw                          # noqa: E402
from kt_verdict import config_fingerprint         # noqa: E402

cfg = json.load(open(r"C:\killtest-rig\config.json", encoding="utf-8"))
print(f"[wrapper] fingerprint from rig config.json = {config_fingerprint(cfg)}   "
      f"(live v3.2 = 63b8561732a5c6bc)")
print("[wrapper] load_config() replaced -- LEGION\\config.json is not opened by this run\n")
kw.load_config = lambda *a, **k: cfg
sys.exit(kw.main(sys.argv[1:]))
