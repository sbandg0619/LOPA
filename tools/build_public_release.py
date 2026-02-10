# tools/build_public_release.py
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# =========================
# helpers
# =========================
def table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def gzip_compress(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    with src.open("rb") as fin, gzip.open(tmp, "wb") as fout:
        shutil.copyfileobj(fin, fout, length=1024 * 1024)
    tmp.replace(dst)


def parse_patch_key(p: str) -> Tuple[int, int, str]:
    """
    '16.2' -> (16,2,'16.2')
    정렬 안정성 확보용. 파싱 실패하면 (0,0,원문)으로 처리.
    """
    s = str(p or "").strip()
    try:
        a, b = s.split(".", 1)
        return (int(a), int(b), s)
    except Exception:
        return (0, 0, s)


def list_patches(src: sqlite3.Connection) -> List[str]:
    if not table_exists(src, "matches"):
        return []
    rows = src.execute(
        "SELECT DISTINCT patch FROM matches WHERE patch IS NOT NULL AND patch != '' ORDER BY patch"
    ).fetchall()
    patches = [r[0] for r in rows if r and r[0]]
    patches.sort(key=lambda x: parse_patch_key(x))
    return patches


def latest_patch_from_matches(src: sqlite3.Connection) -> Optional[str]:
    if not table_exists(src, "matches"):
        return None
    row = src.execute(
        "SELECT patch FROM matches WHERE patch IS NOT NULL AND patch != '' ORDER BY game_creation DESC LIMIT 1"
    ).fetchone()
    return row[0] if row and row[0] else None


def ensure_clean_file(p: Path) -> None:
    try:
        p.unlink()
    except FileNotFoundError:
        pass


def write_sha256_simple(digest: str, sha_path: Path) -> None:
    # 기존 스크립트와 동일 포맷: digest만 한 줄
    sha_path.write_text(digest + "\n", encoding="utf-8")


# =========================
# schema for slim db
# =========================
def create_slim_schema(dst: sqlite3.Connection, *, has_synergy: bool) -> None:
    dst.execute("PRAGMA journal_mode=OFF;")
    dst.execute("PRAGMA synchronous=OFF;")

    # matches
    dst.execute(
        """
        CREATE TABLE IF NOT EXISTS matches (
          match_id TEXT PRIMARY KEY,
          game_creation INTEGER,
          patch TEXT,
          queue_id INTEGER
        )
        """
    )
    dst.execute("CREATE INDEX IF NOT EXISTS idx_matches_patch ON matches(patch);")
    dst.execute("CREATE INDEX IF NOT EXISTS idx_matches_game_creation ON matches(game_creation);")

    # agg_champ_role
    dst.execute(
        """
        CREATE TABLE IF NOT EXISTS agg_champ_role (
          patch TEXT NOT NULL,
          tier TEXT,
          role TEXT NOT NULL,
          champ_id INTEGER NOT NULL,
          games INTEGER NOT NULL,
          wins INTEGER NOT NULL,
          PRIMARY KEY (patch, tier, role, champ_id)
        )
        """
    )

    # agg_matchup_role
    dst.execute(
        """
        CREATE TABLE IF NOT EXISTS agg_matchup_role (
          patch TEXT NOT NULL,
          tier TEXT,
          my_role TEXT NOT NULL,
          enemy_role TEXT NOT NULL,
          my_champ_id INTEGER NOT NULL,
          enemy_champ_id INTEGER NOT NULL,
          games INTEGER NOT NULL,
          wins INTEGER NOT NULL,
          PRIMARY KEY (patch, tier, my_role, enemy_role, my_champ_id, enemy_champ_id)
        )
        """
    )

    # optional: agg_synergy_role (있으면 포함)
    if has_synergy:
        # 컬럼 변형 가능성이 있어 원본 CREATE SQL 복제 방식을 사용
        pass

    dst.commit()


def copy_table_create_sql(src: sqlite3.Connection, dst: sqlite3.Connection, table: str) -> None:
    """
    원본 sqlite_master의 CREATE TABLE SQL을 그대로 가져와서 dst에 생성.
    (agg_synergy_role 같이 컬럼이 변형될 수 있는 테이블에 안전)
    """
    row = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not row or not row[0]:
        return
    ddl = str(row[0]).strip()
    dst.execute(ddl)
    dst.commit()


def copy_table_indexes(src: sqlite3.Connection, dst: sqlite3.Connection, table: str) -> None:
    """
    원본의 해당 table 인덱스들 CREATE SQL을 가능한 범위에서 복사.
    (슬림 DB 성능에 도움)
    """
    rows = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
        (table,),
    ).fetchall()
    for r in rows:
        sql = r[0]
        if not sql:
            continue
        try:
            dst.execute(sql)
        except Exception:
            # 인덱스가 이미 있거나, 호환 안되면 스킵
            pass
    dst.commit()


# =========================
# copy data (patch filtered)
# =========================
def copy_patch_data(
    src: sqlite3.Connection,
    dst: sqlite3.Connection,
    patch: str,
    *,
    include_synergy: bool,
) -> Dict[str, int]:
    stats: Dict[str, int] = {}

    # matches (patch 필터)
    cur = dst.execute(
        """
        INSERT INTO matches(match_id, game_creation, patch, queue_id)
        SELECT match_id, game_creation, patch, queue_id
        FROM matches
        WHERE patch=?
        """,
        (patch,),
    )
    stats["matches_rows"] = cur.rowcount if cur.rowcount is not None else 0

    # agg_champ_role (patch 필터)
    cur = dst.execute(
        """
        INSERT INTO agg_champ_role(patch, tier, role, champ_id, games, wins)
        SELECT patch, tier, role, champ_id, games, wins
        FROM agg_champ_role
        WHERE patch=?
        """,
        (patch,),
    )
    stats["agg_champ_role_rows"] = cur.rowcount if cur.rowcount is not None else 0

    # agg_matchup_role (patch 필터)
    if table_exists(src, "agg_matchup_role"):
        cur = dst.execute(
            """
            INSERT INTO agg_matchup_role(patch, tier, my_role, enemy_role, my_champ_id, enemy_champ_id, games, wins)
            SELECT patch, tier, my_role, enemy_role, my_champ_id, enemy_champ_id, games, wins
            FROM agg_matchup_role
            WHERE patch=?
            """,
            (patch,),
        )
        stats["agg_matchup_role_rows"] = cur.rowcount if cur.rowcount is not None else 0
    else:
        stats["agg_matchup_role_rows"] = 0

    # agg_synergy_role (있으면 patch 필터)
    if include_synergy and table_exists(src, "agg_synergy_role") and table_exists(dst, "agg_synergy_role"):
        cols = [r[1] for r in src.execute("PRAGMA table_info(agg_synergy_role)").fetchall()]
        if cols:
            col_sql = ", ".join(cols)
            q = f"""
              INSERT INTO agg_synergy_role({col_sql})
              SELECT {col_sql}
              FROM agg_synergy_role
              WHERE patch=?
            """
            cur = dst.execute(q, (patch,))
            stats["agg_synergy_role_rows"] = cur.rowcount if cur.rowcount is not None else 0
        else:
            stats["agg_synergy_role_rows"] = 0
    else:
        stats["agg_synergy_role_rows"] = 0

    dst.commit()
    return stats


def vacuum(dst_path: Path) -> None:
    con = sqlite3.connect(str(dst_path))
    try:
        con.execute("VACUUM;")
        con.commit()
    finally:
        con.close()


# =========================
# manifest
# =========================
def build_manifest(
    *,
    latest_patch: str,
    assets: Dict[str, Dict[str, str]],
) -> Dict[str, object]:
    return {
        "latest_patch": latest_patch,
        "assets": assets,
    }


# =========================
# main
# =========================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src_db", required=True, help="source DB path (big DB)")
    ap.add_argument("--out_dir", required=True, help="output dir for release assets")
    ap.add_argument("--patches", default="ALL", help="comma-separated patches or ALL")
    ap.add_argument("--latest_patch", default="", help="override latest_patch in manifest")
    ap.add_argument(
        "--url_prefix",
        default="",
        help="optional: if set, asset url = url_prefix + filename_gz (e.g. https://.../releases/download/<tag>/)",
    )
    ap.add_argument("--include_synergy_if_exists", default="1", help="1/0 (default 1)")

    # NEW: alias 생성 옵션
    ap.add_argument("--no_alias", action="store_true", help="do not create lol_graph_public.db.gz alias")
    ap.add_argument(
        "--alias_patch",
        default="",
        help="which patch to use for alias (default: manifest/latest_patch if built, else latest built patch)",
    )

    args = ap.parse_args()

    src_db = Path(args.src_db).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not src_db.exists():
        raise SystemExit(f"src_db not found: {src_db}")

    include_synergy = str(args.include_synergy_if_exists).strip().lower() in ("1", "true", "yes", "on")

    src = sqlite3.connect(str(src_db))
    try:
        if not table_exists(src, "agg_champ_role"):
            raise SystemExit("src db missing agg_champ_role (cannot build public db)")

        patches_all = list_patches(src)
        if not patches_all:
            raise SystemExit("no patches found in matches table")

        if args.patches.strip().upper() == "ALL":
            patches = patches_all
        else:
            want = [p.strip() for p in args.patches.split(",") if p.strip()]
            patches = [p for p in want if p in patches_all]
            missing = [p for p in want if p not in patches_all]
            if missing:
                print(f"[WARN] requested patches not found in src: {missing}")
            if not patches:
                raise SystemExit("no valid patches selected")

        detected_latest = latest_patch_from_matches(src) or (patches_all[-1] if patches_all else "")
        latest_patch = args.latest_patch.strip() or str(detected_latest or patches[-1])

        # 실제로 빌드한 패치들 중 최신(안전장치)
        latest_built_patch = max(patches, key=lambda x: parse_patch_key(x)) if patches else latest_patch

        has_synergy = include_synergy and table_exists(src, "agg_synergy_role")

        assets: Dict[str, Dict[str, str]] = {}

        for patch in patches:
            # filenames (규칙 A)
            filename_db = f"lol_graph_public_{patch}.db"
            filename_gz = f"lol_graph_public_{patch}.db.gz"
            filename_sha = f"{filename_gz}.sha256"

            db_path = out_dir / filename_db
            gz_path = out_dir / filename_gz
            sha_path = out_dir / filename_sha

            # clean old
            ensure_clean_file(db_path)
            ensure_clean_file(gz_path)
            ensure_clean_file(sha_path)

            # build slim db
            dst = sqlite3.connect(str(db_path))
            try:
                create_slim_schema(dst, has_synergy=False)

                # synergy table: 원본 스키마 그대로 복제
                if has_synergy:
                    copy_table_create_sql(src, dst, "agg_synergy_role")

                # patch-filtered copy
                stats = copy_patch_data(src, dst, patch, include_synergy=has_synergy)

                # 인덱스 복사(가능한 것만)
                copy_table_indexes(src, dst, "agg_champ_role")
                if table_exists(src, "agg_matchup_role"):
                    copy_table_indexes(src, dst, "agg_matchup_role")
                if has_synergy:
                    copy_table_indexes(src, dst, "agg_synergy_role")
            finally:
                dst.close()

            # compact
            vacuum(db_path)

            # gzip + sha
            gzip_compress(db_path, gz_path)
            digest = sha256_file(gz_path)
            write_sha256_simple(digest, sha_path)

            # url
            url_prefix = args.url_prefix.strip()
            if url_prefix and not url_prefix.endswith("/"):
                url_prefix += "/"
            url = (url_prefix + filename_gz) if url_prefix else ""

            assets[patch] = {
                "url": url,
                "sha256": digest,
                "filename_db": filename_db,
                "filename_gz": filename_gz,
                "filename_sha256": filename_sha,
            }

            print(f"[OK] patch={patch} db={filename_db} gz={filename_gz} sha256={digest[:12]}... stats={stats}")

        # manifest
        manifest = build_manifest(latest_patch=latest_patch, assets=assets)
        (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        # NEW: alias 생성 (lol_graph_public.db.gz)
        # - Render 부팅 자동 다운로드가 이 파일명을 기대하는 경우를 위한 "고정 이름"
        if not args.no_alias:
            alias_patch = args.alias_patch.strip()
            if not alias_patch:
                alias_patch = latest_patch if latest_patch in assets else latest_built_patch

            if alias_patch not in assets:
                print(f"[WARN] alias_patch '{alias_patch}' not built; fallback to latest_built_patch '{latest_built_patch}'")
                alias_patch = latest_built_patch

            src_gz = out_dir / assets[alias_patch]["filename_gz"]
            if not src_gz.exists():
                print(f"[WARN] alias source missing: {src_gz} (skip alias)")
            else:
                alias_gz = out_dir / "lol_graph_public.db.gz"
                alias_sha = out_dir / "lol_graph_public.db.gz.sha256"
                ensure_clean_file(alias_gz)
                ensure_clean_file(alias_sha)

                shutil.copy2(src_gz, alias_gz)
                alias_digest = assets[alias_patch]["sha256"]  # 동일 파일 복사이므로 digest 동일
                write_sha256_simple(alias_digest, alias_sha)

                print(f"[ALIAS] patch={alias_patch} -> {alias_gz.name} (sha256={alias_digest[:12]}...)")

        print("\n[DONE]")
        print(f"- out_dir: {out_dir}")
        print(f"- manifest.json latest_patch = {latest_patch}")
        print(f"- assets: {len(assets)} patches")
        if not args.url_prefix.strip():
            print("[NOTE] url_prefix is empty -> manifest assets.url is empty. (릴리즈 업로드 후 URL 채우거나, url_prefix를 주고 다시 생성)")
    finally:
        src.close()


if __name__ == "__main__":
    main()
