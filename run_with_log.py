# run_with_log.py
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python run_with_log.py <log_path> <cmd...>")
        print('Example: python run_with_log.py logs\\collect.log python collector_graph.py --seed "abc#KR1" ...')
        return 2

    log_path = Path(sys.argv[1])
    cmd = sys.argv[2:]

    log_path.parent.mkdir(parents=True, exist_ok=True)

    # 텍스트로 읽어 콘솔+파일 동시 출력
    # (한글/깨짐 대비 errors='replace')
    with log_path.open("w", encoding="utf-8", newline="") as f:
        f.write("[run_with_log] CMD: " + " ".join(cmd) + "\n")
        f.flush()

        p = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        assert p.stdout is not None
        for line in p.stdout:
            # 콘솔
            sys.stdout.write(line)
            sys.stdout.flush()
            # 파일
            f.write(line)
            f.flush()

        return p.wait()


if __name__ == "__main__":
    raise SystemExit(main())
