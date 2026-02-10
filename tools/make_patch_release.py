# -*- coding: utf-8 -*-
"""
tools/make_patch_release.py

목표:
- 단일 DB(lol_graph_public.db 등)에서 특정 patch("16.2") 데이터만 뽑아
  새 sqlite DB를 만들고(.db) gzip(.db.gz) + sha256 + manifest.json 생성

포함 테이블(추천 품질 유지 중심):
- matches (patch 필터)
- participants (matches에 포함된 match_id만)
- match_bans (matches에 포함된 match_id만)  [있으면]
- agg_champ_role (patch 필터)
- agg_matchup_role (patch 필터)             [있으면]
- agg_synergy_role (patch 필터)             [있으면]
- match_tier (patch 필터)                   [있으면]

주의:
- src DB가 "패치별 분리"가 아직 안 돼 있어도, src 안의 patch 컬럼을 이용해 분리 생성함.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Iterable, List


CORE_TABLES = [
    "matches",
    "participants",
    "match_bans",
    "agg_champ_role",
    "agg_matchup_role",
    "agg_synergy_role",
    "match_tier",
]


def _now_ts() -> int:
    return int(time.time())


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _copy_table_schema(src: sqlite3.Connection, dst: sqlite3.Connection, table: str):
    row = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if not row or not row[0]:
        return
    dst.execute(row[0])


def _copy_indexes(src: sqlite3.Connection, dst: sqlite3.Connection, table: str):
    # table 관련 index 생성문 복사
    rows = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
        (table,),
    ).fetchall()
    for (sql,) in rows:
        if sql:
            try:
                dst.execute(sql)
            except Exception:
                # 이미 있거나 호환 안되면 스킵
                pass


def _copy_rows_by_patch(src: sqlite3.Connection, dst: sqlite3.Connection, table: str, patch: str):
    # patch 컬럼이 있는 테이블만 patch=?
    cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})").fetchall()]
    if "patch" not in cols:
        return

    col_list = ", ".join(cols)
    placeholders = ", ".join(["?"] * len(cols))

    cur = src.execute(f"SELECT {col_list} FROM {table} WHERE patch=?", (patch,))
    rows = cur.fetchall()
    if not rows:
        return

    dst.executemany(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})", rows)


def _copy_matches_filtered(src: sqlite3.Connection, dst: sqlite3.Connection, patch: str) -> List[str]:
    cols = [r[1] for r in src.execute("PRAGMA table_info(matches)").fetchall()]
    col_list = ", ".join(cols)
    placeholders = ", ".join(["?"] * len(cols))

    cur = src.execute(f"SELECT {col_list} FROM matches WHERE patch=?", (patch,))
    rows = cur.fetchall()
    if rows:
        dst.executemany(f"INSERT INTO matches ({col_list}) VALUES ({placeholders})", rows)

    mid_idx = cols.index("match_id") if "match_id" in cols else 0
    match_ids = [str(r[mid_idx]) for r in rows] if rows else []
    return match_ids


def _chunks(xs: List[str], n: int) -> Iterable[List[str]]:
    for i in range(0, len(xs), n):
        yield xs[i : i + n]


def _copy_rows_by_match_ids(src: sqlite3.Connection, dst: sqlite3.Connection, table: str, match_ids: List[str]):
    if not match_ids:
        return

    cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})").fetchall()]
    if "match_id" not in cols:
        return

    col_list = ", ".join(cols)
    placeholders = ", ".join(["?"] * len(cols))

    for chunk in _chunks(match_ids, 900):
        qmarks = ", ".join(["?"] * len(chunk))
        cur = src.execute(f"SELECT {col_list} FROM {table} WHERE match_id IN ({qmarks})", tuple(chunk))
        rows = cur.fetchall()
        if rows:
            dst.executemany(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})", rows)


def _vacuum_and_analyze(con: sqlite3.Connection):
    con.execute("ANALYZE;")
    con.commit()
    try:
        con.execute("VACUUM;")
        con.commit()
    except Exception:
        pass


def build_patch_db(src_db: Path, out_db: Path, patch: str):
    if not src_db.exists():
        raise FileNotFoundError(f"src db not found: {src_db}")

    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()

    src = sqlite3.connect(str(src_db))
    dst = sqlite3.connect(str(out_db))

    try:
        dst.execute("PRAGMA journal_mode=OFF;")
        dst.execute("PRAGMA synchronous=OFF;")

        for t in CORE_TABLES:
            if _table_exists(src, t):
                _copy_table_schema(src, dst, t)
        dst.commit()

        match_ids: List[str] = []
        if _table_exists(src, "matches") and _table_exists(dst, "matches"):
            match_ids = _copy_matches_filtered(src, dst, patch)
            dst.commit()

        if _table_exists(src, "participants") and _table_exists(dst, "participants"):
            _copy_rows_by_match_ids(src, dst, "participants", match_ids)
            dst.commit()

        if _table_exists(src, "match_bans") and _table_exists(dst, "match_bans"):
            _copy_rows_by_match_ids(src, dst, "match_bans", match_ids)
            dst.commit()

        for t in ["agg_champ_role", "agg_matchup_role", "agg_synergy_role", "match_tier"]:
            if _table_exists(src, t) and _table_exists(dst, t):
                _copy_rows_by_patch(src, dst, t, patch)
                dst.commit()

        for t in CORE_TABLES:
            if _table_exists(src, t) and _table_exists(dst, t):
                _copy_indexes(src, dst, t)
        dst.commit()

        _vacuum_and_analyze(dst)

        row = dst.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='matches'").fetchone()
        if row:
            cnt = dst.execute("SELECT COUNT(1) FROM matches").fetchone()[0]
            if int(cnt or 0) <= 0:
                raise RuntimeError(
                    f"built DB has 0 matches for patch={patch}. "
                    f"src DB에 해당 patch 데이터가 없거나 patch 값이 다를 수 있음."
                )

    finally:
        try:
            src.close()
        except Exception:
            pass
        try:
            dst.close()
        except Exception:
            pass


def gzip_file(src: Path, dst_gz: Path):
    if dst_gz.exists():
        dst_gz.unlink()
    with src.open("rb") as f_in, gzip.open(str(dst_gz), "wb", compresslevel=9) as f_out:
        shutil.copyfileobj(f_in, f_out)


def write_text(p: Path, s: str):
    p.write_text(s, encoding="utf-8")


def _ensure_clean(p: Path):
    try:
        p.unlink()
    except FileNotFoundError:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="source sqlite db path (e.g. lol_graph_public.db)")
    ap.add_argument("--patch", required=True, help='target patch (e.g. "16.2")')
    ap.add_argument("--variant", required=True, choices=["public", "personal"], help="release variant")
    ap.add_argument("--out_dir", default="release_out", help="output folder")
    ap.add_argument("--tag", default="", help="(optional) release tag to build db_gz_url in manifest")
    ap.add_argument("--repo", default="sbandg0619/LOPA", help='(optional) "owner/repo" for db_gz_url')

    # ✅ NEW: alias 생성 옵션
    ap.add_argument("--no_alias", action="store_true", help="do not create lol_graph_{variant}.db.gz alias")
    args = ap.parse_args()

    src_db = Path(args.src).resolve()
    patch = str(args.patch).strip()
    variant = str(args.variant).strip().lower()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 파일명 규칙 A: lol_graph_{variant}_{patch}.db.gz
    base_name = f"lol_graph_{variant}_{patch}"
    out_db = out_dir / f"{base_name}.db"
    out_gz = out_dir / f"{base_name}.db.gz"
    out_sha = out_dir / f"{base_name}.db.gz.sha256"
    out_manifest = out_dir / "manifest.json"

    print(f"[INFO] src={src_db}")
    print(f"[INFO] patch={patch} variant={variant}")
    print(f"[INFO] out_dir={out_dir}")

    # 1) patch db 생성
    build_patch_db(src_db=src_db, out_db=out_db, patch=patch)
    db_bytes = out_db.stat().st_size
    print(f"[OK] built db: {out_db} ({db_bytes} bytes)")

    # 2) gzip
    gzip_file(out_db, out_gz)
    gz_bytes = out_gz.stat().st_size
    print(f"[OK] gzip: {out_gz} ({gz_bytes} bytes)")

    # 3) sha256 (버전 파일)
    gz_sha = _sha256_file(out_gz)
    write_text(out_sha, gz_sha + "\n")
    print(f"[OK] sha256: {gz_sha}")

    # ✅ NEW: alias 파일 생성 (예: lol_graph_public.db.gz)
    # - 최신 패치 파일과 내용이 동일한 "고정 이름" gzip
    alias_gz = out_dir / f"lol_graph_{variant}.db.gz"
    alias_sha = out_dir / f"lol_graph_{variant}.db.gz.sha256"
    made_alias = False

    if not args.no_alias:
        _ensure_clean(alias_gz)
        _ensure_clean(alias_sha)
        if alias_gz.resolve() != out_gz.resolve():
            shutil.copy2(out_gz, alias_gz)
            write_text(alias_sha, gz_sha + "\n")  # 내용 동일 -> sha256 동일
            made_alias = True
            print(f"[OK] alias: {alias_gz} (sha256 same)")
        else:
            print("[OK] alias skipped (same path)")

    # 4) manifest (release_db가 기대하는 키 포함)
    tag = (args.tag or "").strip()
    repo = (args.repo or "").strip()
    db_gz_url = ""
    if tag and repo:
        db_gz_url = f"https://github.com/{repo}/releases/download/{tag}/{out_gz.name}"

    manifest = {
        "schema_version": 2,
        "generated_at": _now_ts(),
        "variant": variant,
        # ✅ 추가 정보(호환성 깨지지 않음): alias 관련 힌트
        "default_patch": patch,
        "default_filename": (f"lol_graph_{variant}.db.gz" if not args.no_alias else out_gz.name),
        "default_sha256": gz_sha,
        "files": {
            patch: {
                "patch": patch,
                "variant": variant,
                "filename": out_gz.name,
                "bytes": int(gz_bytes),
                "sha256": gz_sha,
                "db_gz_url": db_gz_url,
                "db_gz_sha256": gz_sha,
            }
        },
    }

    write_text(out_manifest, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"[OK] manifest: {out_manifest}")

    # 5) 원본 .db는 보관
    print("[DONE]")
    if made_alias:
        print(f"[DONE] alias created: {alias_gz.name}")


if __name__ == "__main__":
    raise SystemExit(main())
