"""
ktctl.py -- one control panel for the kill test. No more guessing what's running.

  python ktctl.py status     what is running (parent vs worker, log sizes)
  python ktctl.py start      start the kill test + fast sampler (refuses if already up)
  python ktctl.py stop       stop every kill-test process
  python ktctl.py restart    stop, then start
  python ktctl.py watch      status, refreshed every 30s (Ctrl-C to exit)

Design notes:
  * Python on Windows has no fork, so multiprocessing re-launches the same script. That
    makes every worker look like a duplicate process. We detect it via ParentProcessId and
    label it "worker", so you can tell one logical service from two competing copies.
  * `start` refuses to run if the service is already up. That is the whole point -- the
    duplicate-instance mess came from starting things twice.
  * `status` spawns nothing and reads no config. It cannot disturb a running test.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

KT = r"C:\killtest-rig"
LOGS = os.path.join(KT, "logs")

# name -> (script, args, needs_config)
SERVICES = {
    "killtest": ("kt_run.py", ["run"]),
    "fastpath": ("kt_fastpath.py", []),
}


def _ps(cmd: str) -> str:
    """Run a PowerShell one-liner and return stdout (no console window)."""
    p = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
        capture_output=True, text=True, timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return p.stdout or ""


QUERY = (
    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
    "Where-Object { $_.CommandLine -match 'kt_run|kt_fastpath' } | "
    "ForEach-Object { "
    "'{0}|{1}|{2}|{3}' -f $_.ProcessId, $_.ParentProcessId, "
    "([regex]::Match($_.CommandLine,'(kt_[a-z]+\\.py)').Groups[1].Value), "
    "((Get-Process -Id $_.ProcessId).StartTime.ToString('HH:mm:ss')) }"
)


def running() -> list[dict]:
    out = []
    for line in _ps(QUERY).splitlines():
        parts = line.strip().split("|")
        if len(parts) != 4 or not parts[0].isdigit():
            continue
        out.append({"pid": int(parts[0]), "ppid": int(parts[1]),
                    "script": parts[2], "started": parts[3]})
    return out


def alive(pid: int) -> bool:
    return any(r["pid"] == pid for r in running())


def _size_kb(path: str) -> float:
    try:
        return round(os.path.getsize(path) / 1024, 1)
    except OSError:
        return 0.0


def _fresh(path: str) -> str:
    try:
        age = time.time() - os.path.getmtime(path)
    except OSError:
        return "missing"
    if age < 90:
        return f"live ({age:.0f}s ago)"
    if age < 900:
        return f"idle ({age / 60:.0f}m ago)"
    return f"STALE ({age / 3600:.1f}h ago)"


def cmd_status(quiet: bool = False) -> int:
    procs = running()
    print("=" * 88)
    print(f"KILL TEST CONTROL   {time.strftime('%H:%M:%S')}")
    print("=" * 88)

    if not procs:
        print("\n  nothing running.")
    else:
        pids = {p["pid"] for p in procs}
        by_script: dict[str, list[dict]] = {}
        for p in procs:
            by_script.setdefault(p["script"], []).append(p)
        print(f"\n  {'script':<18} {'role':<10} {'pid':>7} {'parent':>8}  started")
        print("  " + "-" * 62)
        for script in sorted(by_script):
            for p in sorted(by_script[script], key=lambda x: x["pid"]):
                # a worker is one whose parent is also a kill-test process
                role = "worker" if p["ppid"] in pids else "MAIN"
                print(f"  {script:<18} {role:<10} {p['pid']:>7} {p['ppid']:>8}  {p['started']}")
        for script in sorted(by_script):
            mains = [p for p in by_script[script] if p["ppid"] not in pids]
            if len(mains) > 1:
                print(f"\n  !! {len(mains)} independent copies of {script} -- data will duplicate.")
                print(f"     keep one:  python ktctl.py stop  then  python ktctl.py start")

    print(f"\n  {'log':<22} {'size':>10}   state")
    print("  " + "-" * 62)
    for fn in ("signals.jsonl", "fastpath.jsonl", "activity.log", "errors.jsonl"):
        p = os.path.join(LOGS, fn)
        print(f"  {fn:<22} {_size_kb(p):>8.1f} KB   {_fresh(p)}")

    sig = os.path.join(LOGS, "signals.jsonl")
    fp = os.path.join(LOGS, "fastpath.jsonl")
    n_sig = n_fp = 0
    try:
        with open(sig, encoding="utf-8", errors="ignore") as f:
            n_sig = sum(1 for l in f if '"kind": "signal"' in l or '"kind":"signal"' in l)
    except OSError:
        pass
    try:
        with open(fp, encoding="utf-8", errors="ignore") as f:
            n_fp = sum(1 for _ in f)
    except OSError:
        pass
    print(f"\n  signals logged : {n_sig}")
    print(f"  fastpath samples: {n_fp}")
    if not quiet:
        print("\n  verdict when the kill test has n>=200 in the primary pool:")
        print("    python kt_verdict.py")
    return 0


def cmd_stop() -> int:
    procs = running()
    if not procs:
        print("  nothing to stop.")
        return 0
    # children first, then parents
    pids = {p["pid"] for p in procs}
    ordered = sorted(procs, key=lambda p: (p["ppid"] not in pids, p["pid"]))
    idlist = ",".join(str(p["pid"]) for p in ordered)
    _ps(f"Stop-Process -Id {idlist} -Force -ErrorAction SilentlyContinue")
    time.sleep(1.5)
    left = running()
    for p in ordered:
        print(f"  stopped {p['script']} (pid {p['pid']})")
    if left:
        print(f"  !! {len(left)} still alive -- rerun stop")
        return 1
    print("  all stopped.")
    return 0


def cmd_start() -> int:
    procs = running()
    pids = {p["pid"] for p in procs}
    already = {}
    for p in procs:
        if p["ppid"] not in pids:                 # only MAIN counts
            already.setdefault(p["script"], p["pid"])

    started = []
    for name, (script, args) in SERVICES.items():
        if script in already:
            print(f"  {script:<18} already running (pid {already[script]}) -- skipped")
            continue
        out = os.path.join(LOGS, f"{name}_stdout.txt")
        err = os.path.join(LOGS, f"{name}_stderr.txt")
        cmd = [sys.executable, os.path.join(KT, script)] + args
        with open(out, "ab") as o, open(err, "ab") as e:
            proc = subprocess.Popen(
                cmd, cwd=KT, stdout=o, stderr=e, stdin=subprocess.DEVNULL,
                creationflags=(getattr(subprocess, "DETACHED_PROCESS", 0)
                               | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)),
            )
        print(f"  {script:<18} started (pid {proc.pid})")
        started.append(proc.pid)
        time.sleep(4)
    if started:
        time.sleep(6)
        print("\n  verifying...")
        cmd_status(quiet=True)
    return 0


def cmd_watch() -> int:
    try:
        while True:
            os.system("cls")
            cmd_status(quiet=True)
            print("\n  (refreshing every 30s -- Ctrl-C to exit)")
            time.sleep(30)
    except KeyboardInterrupt:
        print("\nstopped watching.")
    return 0


def main(argv: list[str]) -> int:
    cmd = (argv[1] if len(argv) > 1 else "status").lower()
    if cmd == "status":
        return cmd_status()
    if cmd == "start":
        return cmd_start()
    if cmd == "stop":
        return cmd_stop()
    if cmd == "restart":
        cmd_stop()
        time.sleep(1)
        return cmd_start()
    if cmd == "watch":
        return cmd_watch()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
