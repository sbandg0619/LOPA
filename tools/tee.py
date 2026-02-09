# tools/tee.py
from __future__ import annotations

import sys
from pathlib import Path

def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write("usage: python tools/tee.py <log_file_path>\n")
        return 2

    log_path = Path(sys.argv[1]).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # binary tee: stdin -> stdout + file
    with log_path.open("ab") as f:
        stdin = sys.stdin.buffer
        stdout = sys.stdout.buffer
        while True:
            chunk = stdin.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)
            f.flush()
            stdout.write(chunk)
            stdout.flush()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
