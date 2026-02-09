# tools/get_patch_from_db.py
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="sqlite db path")
    ap.add_argument("--out", default="", help="optional output file path")
    args = ap.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"ERROR: db not found: {db_path}", file=sys.stderr)
        return 1

    try:
        con = sqlite3.connect(str(db_path), check_same_thread=False)
        try:
            row = con.execute(
                """
                SELECT patch
                FROM matches
                WHERE patch IS NOT NULL AND patch!=''
                ORDER BY game_creation DESC, match_id DESC
                LIMIT 1
                """
            ).fetchone()
        finally:
            con.close()

        patch = (row[0] if row else "") or ""
        patch = str(patch).strip()

        if not patch:
            print("ERROR: patch is empty (matches table has no rows?)", file=sys.stderr)
            return 1

        out = (args.out or "").strip()
        if out:
            p = Path(out)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(patch, encoding="utf-8")

        # stdout도 함께
        sys.stdout.write(patch)
        return 0

    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
