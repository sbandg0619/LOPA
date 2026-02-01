# make_public_db.py
# 목적:
# - 개인 DB -> 공개 배포용 DB 생성
# - 가장 안정적인 방식: backup()로 통째 복제 -> 필요없는 테이블 삭제 -> VACUUM
# - 단, "추천 필수 집계 테이블(agg_champ_role)"이 없으면
#   공개 DB를 만들 수 없으므로, 절대 드롭 진행하지 않고 에러로 종료(사고 방지)

from __future__ import annotations

import argparse
import os
import sqlite3
from typing import List, Set


ALLOW_TABLES_DEFAULT = [
    "matches",
    "agg_champ_role",
    "agg_matchup_role",
    "agg_synergy_role",
    "agg_champ_role_total",
    "match_tier",
]

REQUIRED_TABLES = [
    "agg_champ_role",  # recommend 필수
]

DROP_HINT_TABLES = [
    "players",
    "participants",
    "rank_snapshots",
    "match_participant_rank",
    "crawl_state",
]


def _table_names(con: sqlite3.Connection) -> List[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows if r and r[0]]


def _view_names(con: sqlite3.Connection) -> List[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows if r and r[0]]


def _trigger_names(con: sqlite3.Connection) -> List[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows if r and r[0]]


def _count(con: sqlite3.Connection, table: str) -> int:
    try:
        return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except Exception:
        return -1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="lol_graph_personal.db")
    ap.add_argument("--dst", default="lol_graph_public.db")
    ap.add_argument("--no_vacuum", action="store_true")
    args = ap.parse_args()

    src_path = os.path.abspath(args.src)
    dst_path = os.path.abspath(args.dst)

    if not os.path.exists(src_path):
        raise SystemExit(f"[ERR] src DB not found: {src_path}")

    if os.path.exists(dst_path):
        os.remove(dst_path)

    src = sqlite3.connect(src_path, check_same_thread=False)
    dst = sqlite3.connect(dst_path, check_same_thread=False)

    try:
        dst.execute("PRAGMA journal_mode=WAL")
        dst.execute("PRAGMA synchronous=NORMAL")

        print("[INFO] copying whole DB via sqlite backup() ...")
        src.backup(dst)
        dst.commit()
        print("[INFO] backup done.")

        dst_tables = set(_table_names(dst))
        print("[INFO] dst tables(before prune):", sorted(dst_tables))

        missing_required = [t for t in REQUIRED_TABLES if t not in dst_tables]
        if missing_required:
            # 🚨 사고 방지: 여기서 드롭하면 빈 DB 되는 케이스가 많음
            print("[ERR] 공개 DB 생성 중단: src에 추천 필수 테이블이 없음:", missing_required)
            print("[ERR] 지금 src DB는 '집계가 안 된 DB'이거나 '다른 DB'일 가능성이 큼.")
            print("[ERR] 해결: agg_champ_role 등이 들어있는 DB를 src로 지정하거나, 집계(backfill/build)를 먼저 수행해야 함.")
            print("[HINT] 우선 src DB의 테이블 목록을 확인해줘.")
            raise SystemExit(2)

        allow: Set[str] = set(ALLOW_TABLES_DEFAULT)
        allow = {t for t in allow if t in dst_tables}

        if "matches" not in dst_tables:
            print("[WARN] matches 테이블이 없음. /meta 최신패치/패치목록은 비게 됨(추천은 agg만 있으면 가능).")

        # drop non-allowed tables
        drop_list = [t for t in dst_tables if (not t.startswith("sqlite_")) and (t not in allow)]
        if drop_list:
            print("[INFO] dropping non-allowed tables:", drop_list)
            for t in drop_list:
                try:
                    dst.execute(f"DROP TABLE IF EXISTS {t}")
                except Exception as e:
                    print(f"[WARN] drop table failed {t}: {e}")
            dst.commit()

        # drop all views/triggers for safety
        views = _view_names(dst)
        if views:
            print("[INFO] dropping views:", views)
            for v in views:
                try:
                    dst.execute(f"DROP VIEW IF EXISTS {v}")
                except Exception as e:
                    print(f"[WARN] drop view failed {v}: {e}")
            dst.commit()

        trigs = _trigger_names(dst)
        if trigs:
            print("[INFO] dropping triggers:", trigs)
            for tg in trigs:
                try:
                    dst.execute(f"DROP TRIGGER IF EXISTS {tg}")
                except Exception as e:
                    print(f"[WARN] drop trigger failed {tg}: {e}")
            dst.commit()

        if not args.no_vacuum:
            print("[INFO] running VACUUM ... (may take a bit)")
            dst.execute("VACUUM")
            dst.commit()
            print("[INFO] VACUUM done.")
        else:
            print("[INFO] skip VACUUM (--no_vacuum)")

        final_tables = _table_names(dst)
        print("[INFO] dst tables(after prune):", final_tables)

        print("[INFO] dst table counts:")
        for t in sorted(allow):
            print(f"  - {t}: {_count(dst, t)}")

        print(f"[OK] created public DB: {dst_path}")

    finally:
        try:
            dst.close()
        except Exception:
            pass
        try:
            src.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
