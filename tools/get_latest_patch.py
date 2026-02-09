# tools/get_latest_patch.py
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests


VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"


def pick_latest_major_minor(versions: list[str]) -> str:
    seen: list[str] = []
    for v in versions or []:
        parts = (v or "").split(".")
        if len(parts) < 2:
            continue
        mm = f"{parts[0]}.{parts[1]}"
        if not mm:
            continue
        if not seen or mm != seen[-1]:
            if mm not in seen:
                seen.append(mm)
        if seen:
            break
    return seen[0] if seen else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="", help="optional output file path to write patch")
    ap.add_argument("--timeout", type=float, default=10.0)
    args = ap.parse_args()

    try:
        r = requests.get(VERSIONS_URL, timeout=float(args.timeout))
        r.raise_for_status()
        versions = r.json()
        if not isinstance(versions, list):
            print("ERROR: versions.json is not a list", file=sys.stderr)
            return 1
        patch = pick_latest_major_minor([str(x) for x in versions])
        if not patch:
            print("ERROR: failed to pick latest patch", file=sys.stderr)
            return 1

        # stdout: patch only
        sys.stdout.write(patch)

        # optional file write (for CMD safety)
        out = (args.out or "").strip()
        if out:
            p = Path(out)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(patch, encoding="utf-8")
        return 0

    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
