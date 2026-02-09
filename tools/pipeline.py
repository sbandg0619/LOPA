# tools/pipeline.py
from __future__ import annotations

import argparse
import os
import sys
import time
import random
import subprocess
import threading
import queue
import signal
from pathlib import Path

import requests


def truthy(v: str | None) -> bool:
    s = (v or "").strip().lower()
    return s in ("1", "true", "yes", "y", "on")


def get_latest_patch_ddragon(timeout: float = 10.0) -> str:
    # 최신 버전 예: "16.3.1" -> patch "16.3"
    url = "https://ddragon.leagueoflegends.com/api/versions.json"
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    versions = r.json()
    if not versions:
        raise RuntimeError("ddragon versions empty")
    v = str(versions[0])
    parts = v.split(".")
    if len(parts) < 2:
        raise RuntimeError(f"unexpected ddragon version: {v}")
    return f"{parts[0]}.{parts[1]}"


class TeeLogger:
    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.f = log_path.open("a", encoding="utf-8", errors="replace")

    def close(self):
        try:
            self.f.close()
        except Exception:
            pass

    def write_line(self, s: str):
        if not s.endswith("\n"):
            s += "\n"
        sys.stdout.write(s)
        sys.stdout.flush()
        self.f.write(s)
        self.f.flush()


def _force_kill_tree(pid: int):
    if os.name != "nt":
        try:
            os.kill(pid, signal.SIGKILL)  # type: ignore[attr-defined]
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


def _is_ctrlc_exit(rc: int) -> bool:
    # Windows Ctrl+C 종료코드: 0xC000013A == 3221225786 == -1073741510(signed)
    return rc in (3221225786, -1073741510)


def run_cmd_live(
    cmd: list[str],
    log: TeeLogger,
    *,
    allow_ctrlc_success: bool = False,
) -> int:
    """
    stdout를 실시간으로 읽어 콘솔+로그에 출력.

    ✅ 핵심:
    - CREATE_NEW_PROCESS_GROUP 사용하지 않음 => Ctrl+C가 child(collector)까지 "자연 전달"되게 함
    - pipeline은 Ctrl+C를 잡아도 죽지 않고 child가 종료될 때까지 대기
    - Ctrl+C를 한 번 더 누르면 강제 kill

    반환: rc (allow_ctrlc_success=True && Ctrl+C 종료코드면 0으로 보정)
    """
    log.write_line(f"[CMD] {' '.join(cmd)}")

    show_wait = truthy(os.getenv("PIPELINE_SHOW_WAIT", "0"))
    wait_every = float(os.getenv("PIPELINE_WAIT_EVERY", "8.0"))

    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
        # ✅ 여기서 creationflags 안 줌 (중요)
    )

    q: "queue.Queue[str]" = queue.Queue()

    def reader():
        try:
            assert p.stdout is not None
            for line in p.stdout:
                q.put(line)
        except Exception:
            pass

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    last_out = time.time()
    ctrlc_requested = False
    warned = False

    try:
        while True:
            try:
                line = q.get(timeout=0.2)
                last_out = time.time()
                log.write_line(line.rstrip("\n"))
            except queue.Empty:
                if p.poll() is not None and q.empty():
                    break

                if show_wait:
                    now = time.time()
                    if now - last_out >= wait_every:
                        log.write_line("[WAIT] child is still running... (no stdout yet)")
                        last_out = now

    except KeyboardInterrupt:
        # ✅ 1st Ctrl+C: child가 이미 Ctrl+C를 받도록 "자연 전달"되었고,
        # pipeline은 죽지 말고 종료까지 기다린다.
        ctrlc_requested = True
        log.write_line("[pipeline] Ctrl+C received. Waiting child to exit gracefully... (press Ctrl+C again to FORCE kill)")

        while True:
            try:
                try:
                    line = q.get(timeout=0.2)
                    log.write_line(line.rstrip("\n"))
                except queue.Empty:
                    if p.poll() is not None and q.empty():
                        break
            except KeyboardInterrupt:
                # ✅ 2nd Ctrl+C: 강제 kill
                if not warned:
                    warned = True
                    log.write_line("[pipeline] Ctrl+C x2 => force killing child tree...")
                _force_kill_tree(p.pid)
                break

    rc = p.wait()

    try:
        t.join(timeout=1.0)
    except Exception:
        pass

    rc = int(rc)

    # Ctrl+C 종료코드라면 collector 단계에서는 성공으로 취급 가능
    if allow_ctrlc_success and ctrlc_requested and _is_ctrlc_exit(rc):
        rc = 0

    return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.getenv("DB", "lol_graph_public.db"))
    ap.add_argument("--seed", default=os.getenv("SEED", "파뽀마블#KRI"))
    ap.add_argument("--mode", default=os.getenv("COLLECT_MODE", "dev"))
    args, _ = ap.parse_known_args()

    root = Path(__file__).resolve().parents[1]
    logs_dir = root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    profile = (os.getenv("APP_PROFILE") or "personal").strip().lower()
    ts = time.strftime("%Y%m%d_%H%M%S")
    rid = random.randint(10000, 99999)
    log_path = logs_dir / f"pipeline_{profile}_{ts}_{rid}.log"

    log = TeeLogger(log_path)
    try:
        log.write_line(f'[INFO] Logging to: "{log_path}"')

        py_exe = os.getenv("PY_EXE") or os.getenv("PY_CMD") or sys.executable
        py_exe = py_exe.strip().strip('"')

        # 0) latest patch
        log.write_line("[DEBUG] fetching latest patch from ddragon...")
        latest_patch = get_latest_patch_ddragon(timeout=10.0)
        log.write_line(f"[INFO] LATEST_PATCH={latest_patch}")
        log.write_line("")

        db = args.db
        seed = args.seed
        mode = args.mode

        # 1) collector
        log.write_line("[STEP] COLLECTOR start...")
        cmd_collect = [
            py_exe, "-u", str(root / "collector_graph.py"),
            "--seed", seed,
            "--db", db,
            "--latest_only",
            "--mode", mode,
        ]
        rc = run_cmd_live(cmd_collect, log, allow_ctrlc_success=True)
        log.write_line(f"[STEP] COLLECTOR end. rc={rc}")
        log.write_line("")
        if rc != 0:
            log.write_line(f"[ERROR] COLLECTOR failed. rc={rc}")
            return rc

        # 2) backfills
        log.write_line("[STEP] BACKFILL champ_role...")
        cmd1 = [py_exe, "-u", str(root / "backfill_champ_role.py"), "--db", db, "--patch", latest_patch, "--tier", "ALL"]
        rc1 = run_cmd_live(cmd1, log)
        log.write_line(f"[STEP] BACKFILL champ_role end. rc={rc1}")
        log.write_line("")
        if rc1 != 0:
            log.write_line("[ERROR] backfill_champ_role failed")
            return rc1

        log.write_line("[STEP] BACKFILL matchups...")
        cmd2 = [py_exe, "-u", str(root / "backfill_matchups.py"), "--db", db, "--patch", latest_patch, "--tier", "ALL"]
        rc2 = run_cmd_live(cmd2, log)
        log.write_line(f"[STEP] BACKFILL matchups end. rc={rc2}")
        log.write_line("")
        if rc2 != 0:
            log.write_line("[ERROR] backfill_matchups failed")
            return rc2

        log.write_line("[STEP] BUILD synergy...")
        cmd3 = [py_exe, "-u", str(root / "build_synergy.py"), "--db", db, "--patch", latest_patch, "--tier", "ALL"]
        rc3 = run_cmd_live(cmd3, log)
        log.write_line(f"[STEP] BUILD synergy end. rc={rc3}")
        log.write_line("")
        if rc3 != 0:
            log.write_line("[ERROR] build_synergy failed")
            return rc3

        # 3) release
        do_release = truthy(os.getenv("DO_RELEASE", "0"))
        if not do_release:
            log.write_line("[STEP] RELEASE skipped (DO_RELEASE=0)")
        else:
            variant = (os.getenv("RELEASE_VARIANT") or "public").strip()
            out_dir = (os.getenv("RELEASE_OUT_DIR") or "release_out").strip()
            src_abs = str((root / db).resolve())
            out_abs = str((root / out_dir).resolve())

            log.write_line("[STEP] RELEASE build patch db + gz...")
            cmd_rel = [
                py_exe, "-u", str(root / "tools" / "make_patch_release.py"),
                "--src", src_abs,
                "--patch", latest_patch,
                "--variant", variant,
                "--out_dir", out_abs,
            ]
            rc4 = run_cmd_live(cmd_rel, log)
            log.write_line(f"[STEP] RELEASE end. rc={rc4}")
            log.write_line("")
            if rc4 != 0:
                log.write_line("[ERROR] release failed")
                return rc4
            log.write_line(f"[OK] RELEASE_OUT={out_abs}")

        log.write_line("")
        log.write_line(f"[OK] PIPELINE finished. LATEST_PATCH={latest_patch}")
        return 0

    finally:
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
