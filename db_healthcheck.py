# db_healthcheck.py
from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _count(con: sqlite3.Connection, sql: str, params=()) -> int:
    row = con.execute(sql, params).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _one(con: sqlite3.Connection, sql: str, params=()):
    return con.execute(sql, params).fetchone()


def _many(con: sqlite3.Connection, sql: str, params=(), limit: int = 10):
    return con.execute(sql + f" LIMIT {int(limit)}", params).fetchall()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="lol_graph.db")
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()

    con = sqlite3.connect(args.db, check_same_thread=False)

    print("==================================================")
    print(f"[DB HEALTHCHECK] db={args.db}")
    print("==================================================")

    # --- table presence ---
    must_tables = [
        "players",
        "matches",
        "participants",
        "match_bans",
        "agg_champ_role",
        "agg_matchup_role",
        "crawl_state",
        "rank_snapshots",
        "match_participant_rank",
        "match_tier",
    ]
    print("\n[TABLES]")
    for t in must_tables:
        print(f"- {t}: {'OK' if _table_exists(con, t) else 'MISSING'}")

    # --- basic counts ---
    print("\n[COUNTS]")
    if _table_exists(con, "matches"):
        print(f"- matches: {_count(con, 'SELECT COUNT(*) FROM matches')}")
    if _table_exists(con, "participants"):
        print(f"- participants: {_count(con, 'SELECT COUNT(*) FROM participants')}")
    if _table_exists(con, "players"):
        print(f"- players: {_count(con, 'SELECT COUNT(*) FROM players')}")
    if _table_exists(con, "match_bans"):
        print(f"- match_bans: {_count(con, 'SELECT COUNT(*) FROM match_bans')}")
    if _table_exists(con, "agg_champ_role"):
        print(f"- agg_champ_role: {_count(con, 'SELECT COUNT(*) FROM agg_champ_role')}")
    if _table_exists(con, "agg_matchup_role"):
        print(f"- agg_matchup_role: {_count(con, 'SELECT COUNT(*) FROM agg_matchup_role')}")

    # --- patch distribution ---
    print("\n[PATCH DISTRIBUTION] (matches)")
    if _table_exists(con, "matches"):
        rows = con.execute(
            "SELECT patch, COUNT(*) AS n FROM matches GROUP BY patch ORDER BY n DESC"
        ).fetchall()
        if not rows:
            print("- (no rows)")
        else:
            for patch, n in rows[: max(10, args.limit)]:
                print(f"- patch={patch}: {n}")

            latest = _one(con, "SELECT patch FROM matches ORDER BY game_creation DESC LIMIT 1")
            if latest and latest[0]:
                print(f"- latest_by_game_creation: {latest[0]}")

    # --- participants per match sanity ---
    print("\n[PARTICIPANTS PER MATCH] (expected ~10)")
    if _table_exists(con, "participants"):
        row = _one(
            con,
            """
            SELECT
              COUNT(*) AS part_rows,
              COUNT(DISTINCT match_id) AS match_cnt
            FROM participants
            """,
        )
        if row and row[1]:
            part_rows, match_cnt = int(row[0]), int(row[1])
            avg = part_rows / float(match_cnt) if match_cnt else 0.0
            print(f"- distinct_matches_in_participants: {match_cnt}")
            print(f"- total_participant_rows: {part_rows}")
            print(f"- avg_participants_per_match: {avg:.2f}")

        # show some bad matches (not 10)
        bad = con.execute(
            """
            SELECT match_id, COUNT(*) AS c
            FROM participants
            GROUP BY match_id
            HAVING c != 10
            ORDER BY c ASC
            LIMIT 20
            """
        ).fetchall()
        if bad:
            print("- WARNING: matches with participant count != 10 (showing up to 20):")
            for mid, c in bad:
                print(f"  * {mid}: {c}")

    # --- bans per match sanity ---
    print("\n[BANS PER MATCH] (expected ~10: 5 per team x 2)")
    if _table_exists(con, "match_bans"):
        row = _one(
            con,
            """
            SELECT
              COUNT(*) AS ban_rows,
              COUNT(DISTINCT match_id) AS match_cnt
            FROM match_bans
            """,
        )
        if row and row[1]:
            ban_rows, match_cnt = int(row[0]), int(row[1])
            avg = ban_rows / float(match_cnt) if match_cnt else 0.0
            print(f"- distinct_matches_in_match_bans: {match_cnt}")
            print(f"- total_ban_rows: {ban_rows}")
            print(f"- avg_bans_per_match: {avg:.2f}")

        bad = con.execute(
            """
            SELECT match_id, COUNT(*) AS c
            FROM match_bans
            GROUP BY match_id
            HAVING c NOT IN (10)
            ORDER BY c ASC
            LIMIT 20
            """
        ).fetchall()
        if bad:
            print("- WARNING: matches with bans count != 10 (showing up to 20):")
            for mid, c in bad:
                print(f"  * {mid}: {c}")

    # --- top champs by sample (agg_champ_role) ---
    print("\n[TOP CHAMPS BY GAMES] (agg_champ_role)")
    if _table_exists(con, "agg_champ_role"):
        rows = _many(
            con,
            """
            SELECT patch, COALESCE(tier,'ALL') AS tier, role, champ_id, games, wins,
                   ROUND(100.0 * wins / NULLIF(games,0), 2) AS wr
            FROM agg_champ_role
            ORDER BY games DESC
            """,
            limit=args.limit,
        )
        if not rows:
            print("- (no rows)")
        else:
            for r in rows:
                print(f"- patch={r[0]} tier={r[1]} role={r[2]} champ={r[3]} games={r[4]} wr={r[6]}%")

    # --- top matchups by sample (agg_matchup_role) ---
    print("\n[TOP MATCHUPS BY GAMES] (agg_matchup_role)")
    if _table_exists(con, "agg_matchup_role"):
        rows = _many(
            con,
            """
            SELECT patch, COALESCE(tier,'ALL') AS tier, my_role, enemy_role,
                   my_champ_id, enemy_champ_id, games, wins,
                   ROUND(100.0 * wins / NULLIF(games,0), 2) AS wr
            FROM agg_matchup_role
            ORDER BY games DESC
            """,
            limit=args.limit,
        )
        if not rows:
            print("- (no rows)")
        else:
            for r in rows:
                print(
                    f"- patch={r[0]} tier={r[1]} {r[2]} vs {r[3]} "
                    f"my={r[4]} enemy={r[5]} games={r[6]} wr={r[8]}%"
                )

    # --- crawl_state quick peek ---
    print("\n[CRAWL STATE]")
    if _table_exists(con, "crawl_state"):
        rows = con.execute(
            "SELECT k, substr(v,1,120) AS v, updated_at FROM crawl_state ORDER BY updated_at DESC NULLS LAST LIMIT 20"
        ).fetchall()
        if not rows:
            print("- (empty)")
        else:
            for k, v, ts in rows:
                print(f"- {k}: {v} (updated_at={ts})")

    print("\n[OK] healthcheck done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
