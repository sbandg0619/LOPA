from __future__ import annotations

import argparse
import gzip
import json
import hashlib
import os
import sqlite3
import time
from pathlib import Path
from typing import List, Tuple


# -------------------------
# small helpers
# -------------------------
def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def gzip_compress(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("rb") as f_in, gzip.open(dst, "wb", compresslevel=9) as f_out:
        while True:
            b = f_in.read(1024 * 1024)
            if not b:
                break
            f_out.write(b)


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def list_tables(con: sqlite3.Connection) -> List[str]:
    rows = con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    return [r[0] for r in rows if r and r[0]]


def get_create_sql(con: sqlite3.Connection, table: str) -> str:
    row = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return (row[0] or "").strip() if row else ""


def get_index_sqls(con: sqlite3.Connection, table: str) -> List[str]:
    # user-created indexes only (exclude autoindex)
    rows = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
        (table,),
    ).fetchall()
    out = []
    for r in rows:
        s = (r[0] or "").strip()
        if s:
            out.append(s)
    return out


def copy_table_schema(src: sqlite3.Connection, dst: sqlite3.Connection, table: str) -> None:
    create_sql = get_create_sql(src, table)
    if not create_sql:
        return
    dst.execute(create_sql)

    for idx_sql in get_index_sqls(src, table):
        dst.execute(idx_sql)


def copy_all_schema(src: sqlite3.Connection, dst: sqlite3.Connection) -> None:
    for t in list_tables(src):
        copy_table_schema(src, dst, t)
    dst.commit()


def copy_table_data_all(src: sqlite3.Connection, dst: sqlite3.Connection, table: str) -> None:
    dst.execute(f'INSERT INTO "{table}" SELECT * FROM "{table}"', ())


def copy_table_data_where(src: sqlite3.Connection, dst: sqlite3.Connection, table: str, where_sql: str, params: Tuple) -> None:
    # assumes same columns
    dst.execute(f'INSERT INTO "{table}" SELECT * FROM "{table}" WHERE {where_sql}', params)


def vacuum(dst_path: Path) -> None:
    con = sqlite3.connect(str(dst_path))
    try:
        con.execute("VACUUM;")
    finally:
        con.close()


# -------------------------
# patch filtering policy
# -------------------------
#  ּ     Ʒ     ̺     "patch  ÷ "    ־    ǹ̰      .
# - matches: patch     
# - agg_champ_role: patch     
# - match_tier: patch     (      )
# - agg_matchup_role: patch     (      )
# - agg_synergy_role: patch     (      )
PATCH_FILTER_TABLES = {
    "matches": ("patch = ?",),
    "agg_champ_role": ("patch = ?",),
    "match_tier": ("patch = ?",),
    "agg_matchup_role": ("patch = ?",),
    "agg_synergy_role": ("patch = ?",),
}


# participants   patch  ÷         match_id   matches        ؾ    .
def copy_participants_for_patch(src: sqlite3.Connection, dst: sqlite3.Connection, patch: str) -> None:
    if not table_exists(src, "participants") or not table_exists(src, "matches"):
        return
    # participants (match_id) join matches(patch)
    dst.execute(
        """
        INSERT INTO participants
        SELECT p.*
        FROM participants p
        JOIN matches m ON m.match_id = p.match_id
        WHERE m.patch = ?
        """,
        (patch,),
    )


def copy_match_participant_rank_for_patch(src: sqlite3.Connection, dst: sqlite3.Connection, patch: str) -> None:
    if not table_exists(src, "match_participant_rank") or not table_exists(src, "matches"):
        return
    dst.execute(
        """
        INSERT INTO match_participant_rank
        SELECT r.*
        FROM match_participant_rank r
        JOIN matches m ON m.match_id = r.match_id
        WHERE m.patch = ?
        """,
        (patch,),
    )


def copy_match_bans_for_patch(src: sqlite3.Connection, dst: sqlite3.Connection, patch: str) -> None:
    if not table_exists(src, "match_bans") or not table_exists(src, "matches"):
        return
    dst.execute(
        """
        INSERT INTO match_bans
        SELECT b.*
        FROM match_bans b
        JOIN matches m ON m.match_id = b.match_id
        WHERE m.patch = ?
        """,
        (patch,),
    )


# players / rank_snapshots / crawl_state    patch      ӵ        :
# - public                     ʿ       ( 뷮   Ŀ  )
# -    ο뿣  ־       ,                  ̸     ܰ   ̵ 
DEFAULT_EXCLUDE_TABLES = {"players", "rank_snapshots", "crawl_state"}


def build_patch_db(src_db: Path, out_db: Path, patch: str, *, include_nonpatch_tables: bool) -> None:
    if out_db.exists():
        out_db.unlink()

    src = sqlite3.connect(str(src_db))
    dst = sqlite3.connect(str(out_db))
    try:
        # speed
        dst.execute("PRAGMA journal_mode=WAL;")
        dst.execute("PRAGMA synchronous=NORMAL;")

        # 1) schema copy
        copy_all_schema(src, dst)

        # 2) data copy
        tables = list_tables(src)
        for t in tables:
            if not include_nonpatch_tables and t in DEFAULT_EXCLUDE_TABLES:
                continue

            if t in PATCH_FILTER_TABLES and table_exists(src, t):
                dst.execute(f'INSERT INTO "{t}" SELECT * FROM "{t}" WHERE patch = ?', (patch,))
                continue

            if t == "participants":
                copy_participants_for_patch(src, dst, patch)
                continue

            if t == "match_participant_rank":
                copy_match_participant_rank_for_patch(src, dst, patch)
                continue

            if t == "match_bans":
                copy_match_bans_for_patch(src, dst, patch)
                continue

            #           ̺  ó  :
            # include_nonpatch_tables=True           °       
            if include_nonpatch_tables:
                copy_table_data_all(src, dst, t)

        dst.commit()

    finally:
        dst.close()
        src.close()

    # 3) vacuum for size
    vacuum(out_db)


def update_manifest(outdir: Path, patch: str, variant: str, gz_name: str, digest: str, bytes_: int) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    manifest_path = outdir / "manifest.json"

    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8") or "{}")
        except Exception:
            manifest = {}
    else:
        manifest = {}

    manifest.setdefault("schema_version", 1)
    manifest.setdefault("generated_at", int(time.time()))
    manifest.setdefault("variant", variant)
    manifest.setdefault("files", {})

    manifest["generated_at"] = int(time.time())
    manifest["variant"] = variant

    manifest["files"][patch] = {
        "patch": patch,
        "variant": variant,
        "filename": gz_name,
        "sha256": digest,
        "bytes": int(bytes_),
    }

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="source db (e.g. lol_graph_public.db)")
    ap.add_argument("--patch", required=True, help="patch label (e.g. 16.2)")
    ap.add_argument("--variant", default="public", choices=["public", "personal"])
    ap.add_argument("--outdir", default="release_out")
    ap.add_argument("--keep_patch_db", action="store_true", help="keep generated patch db (not only gz)")
    ap.add_argument(
        "--include_nonpatch_tables",
        action="store_true",
        help="copy non-patch tables too (bigger). default: False",
    )
    args = ap.parse_args()

    src_db = Path(args.src)
    if not src_db.exists():
        raise SystemExit(f"DB not found: {src_db}")

    patch = str(args.patch).strip()
    variant = str(args.variant).strip().lower()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    patch_db_name = f"lol_graph_{variant}_{patch}.db"
    patch_db_path = outdir / patch_db_name

    print("==================================================")
    print("LOPA release asset builder (single DB -> patch DB -> gz)")
    print(f"src_db   = {src_db}")
    print(f"patch    = {patch}")
    print(f"variant  = {variant}")
    print(f"outdir   = {outdir}")
    print(f"include_nonpatch_tables = {bool(args.include_nonpatch_tables)}")
    print("==================================================")

    print(f"[1] build patch db: {patch_db_path}")
    build_patch_db(src_db, patch_db_path, patch, include_nonpatch_tables=bool(args.include_nonpatch_tables))

    gz_name = f"lol_graph_{variant}_{patch}.db.gz"  # rule A
    gz_path = outdir / gz_name
    print(f"[2] gzip: {patch_db_path} -> {gz_path}")
    gzip_compress(patch_db_path, gz_path)

    print("[3] sha256...")
    digest = sha256_file(gz_path)
    sha_path = outdir / f"{gz_name}.sha256"
    sha_path.write_text(f"{digest}  {gz_name}\n", encoding="utf-8")

    print("[4] manifest.json...")
    manifest_path = update_manifest(outdir, patch, variant, gz_name, digest, gz_path.stat().st_size)

    if not args.keep_patch_db:
        try:
            patch_db_path.unlink()
            print(f"[5] removed temp patch db: {patch_db_path}")
        except Exception:
            pass

    print("OK:")
    print(f" - {gz_path}")
    print(f" - {sha_path}")
    print(f" - {manifest_path}")


if __name__ == "__main__":
    main()
