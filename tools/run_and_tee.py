# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import os
import sys
import time
import signal
import threading
import subprocess
from datetime import datetime
from pathlib import Path


def _truthy(v: str | None) -> bool:
    s = (v or "").strip().lower()
    return s in ("1", "true", "yes", "y", "on")


# -------------------------
# log path helper
# -------------------------
def _make_log_path(logdir: str, prefix: str) -> Path:
    ld = Path(logdir).resolve()
    ld.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rnd = f"{int(time.time()*1000)}_{os.getpid()}"
    return ld / f"{prefix}_{ts}_{rnd}.log"


# -------------------------
# reader thread
# -------------------------
def _reader_thread(proc: subprocess.Popen, log_f):
    try:
        for line in proc.stdout:
            if not line:
                break
            sys.stdout.write(line)
            sys.stdout.flush()
            log_f.write(line)
            log_f.flush()
    except Exception as e:
        try:
            msg = f"\n[run_and_tee] reader exception: {type(e).__name__}: {e}\n"
            sys.stdout.write(msg)
            sys.stdout.flush()
            log_f.write(msg)
            log_f.flush()
        except Exception:
            pass


# -------------------------
# Windows: force kill process tree
# -------------------------
def _force_kill_tree(pid: int):
    if os.name != "nt":
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass
        return

    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        pass


# -------------------------
# SIGINT handler
# -------------------------
_SIGINT_COUNT = 0
_SIGINT_LAST_TS = 0.0
_PROC: subprocess.Popen | None = None  # set in main()


def _on_sigint(signum, frame):
    global _SIGINT_COUNT, _SIGINT_LAST_TS, _PROC
    now = time.time()
    if now - _SIGINT_LAST_TS > 2.0:
        _SIGINT_COUNT = 0
    _SIGINT_COUNT += 1
    _SIGINT_LAST_TS = now

    if _SIGINT_COUNT == 1:
        # 1st Ctrl+C: forward to child (Windows best-effort), do NOT raise KeyboardInterrupt
        if os.name == "nt" and _PROC is not None:
            try:
                _PROC.send_signal(signal.CTRL_C_EVENT)
            except Exception:
                # best-effort only
                pass

        sys.stdout.write(
            "\n[run_and_tee] Ctrl+C received (forwarded to child). "
            "Press Ctrl+C again within 2 seconds to force-kill EVERYTHING.\n"
        )
        sys.stdout.flush()
        return
    # 2nd Ctrl+C handled in main loop (force kill)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--logdir", default="logs")
    ap.add_argument("--prefix", default="pipeline")
    ap.add_argument("--log", default="")
    ap.add_argument("--encoding", default="utf-8")
    ap.add_argument("cmd", nargs=argparse.REMAINDER, help="use: -- <command...>")
    args = ap.parse_args()

    cmd = args.cmd
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print(
            "Usage: run_and_tee.py --logdir logs --prefix pipeline -- cmd.exe /d /c call RUN_PIPELINE_COMMON.bat",
            flush=True,
        )
        return 2

    # install SIGINT handler
    try:
        signal.signal(signal.SIGINT, _on_sigint)
    except Exception:
        pass

    if args.log.strip():
        log_path = Path(args.log.strip().strip('"')).resolve()
        log_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        log_path = _make_log_path(args.logdir, args.prefix)

    # ✅ 중복 방지: 기본은 log path를 여기서 출력하지 않음
    # 필요하면 RUN_TEE_PRINT_LOGPATH=1 로 켤 수 있음
    if _truthy(os.getenv("RUN_TEE_PRINT_LOGPATH", "0")):
        print(f'[INFO] Logging to: "{log_path}"', flush=True)

    print("=== run_and_tee start ===", flush=True)
    print("CMD:", " ".join(cmd), flush=True)

    creationflags = 0
    if os.name == "nt":
        # ✅ CTRL_C_EVENT forward 하려면 process group 필요
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    with log_path.open("w", encoding=args.encoding, errors="replace", newline="") as log_f:
        global _PROC
        _PROC = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=None,
            text=True,
            encoding=args.encoding,
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )

        t = threading.Thread(target=_reader_thread, args=(_PROC, log_f), daemon=True)
        t.start()

        # main wait loop
        while True:
            rc = _PROC.poll()
            if rc is not None:
                break

            if _SIGINT_COUNT >= 2:
                sys.stdout.write("[run_and_tee] Force-killing process tree...\n")
                sys.stdout.flush()
                log_f.write("[run_and_tee] Force-killing process tree...\n")
                log_f.flush()
                _force_kill_tree(_PROC.pid)
                time.sleep(0.2)
                break

            time.sleep(0.1)

        try:
            t.join(timeout=2.0)
        except Exception:
            pass

        rc2 = _PROC.poll()
        if rc2 is None:
            try:
                rc2 = _PROC.wait(timeout=2.0)
            except Exception:
                rc2 = 1

        print(f"=== run_and_tee end rc={rc2} ===", flush=True)
        return int(rc2 if rc2 is not None else 1)


if __name__ == "__main__":
    raise SystemExit(main())
