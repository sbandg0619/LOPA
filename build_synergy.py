from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from typing import Optional, Tuple, List

ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]


def _connect(db: str) -> sqlite3.Connection:
    con = sqlite3.connect(db, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con


def _ensure_tables(con: sqlite3.Connection):
    # done table
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS backfill_done (
          job_id TEXT NOT NULL,
          match_id TEXT NOT NULL,
          done_at INTEGER NOT NULL DEFAULT (CAST(strftime('%s','now') AS INTEGER)),
          PRIMARY KEY (job_id, match_id)
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_backfill_done_job ON backfill_done(job_id);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_backfill_done_match ON backfill_done(match_id);")

    # synergy table
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS agg_synergy_role (
          patch TEXT NOT NULL,
          tier TEXT,
          my_role TEXT NOT NULL,
          ally_role TEXT NOT NULL,
          my_champ_id INTEGER NOT NULL,
          ally_champ_id INTEGER NOT NULL,
          games INTEGER NOT NULL,
          wins INTEGER NOT NULL,
          PRIMARY KEY (patch, tier, my_role, ally_role, my_champ_id, ally_champ_id)
        )
        """
    )
    con.commit()


def _job_id(patch: str, tier: str) -> str:
    return f"synergy|patch={patch.upper()}|tier={tier.upper()}"


def _patch_pat(patch: str) -> str:
    return "%" if patch.upper() == "ALL" else patch


def _force_tier(tier: str) -> Optional[str]:
    return None if tier.upper() == "ALL" else tier.upper()


def _reset(con: sqlite3.Connection, job_id: str, patch: str, tier: str):
    patch_pat = _patch_pat(patch)
    ft = _force_tier(tier)

    con.execute("DELETE FROM backfill_done WHERE job_id=?", (job_id,))

    if ft is None:
        con.execute("DELETE FROM agg_synergy_role WHERE patch LIKE ?", (patch_pat,))
    else:
        con.execute("DELETE FROM agg_synergy_role WHERE patch LIKE ? AND tier=?", (patch_pat, ft))
    con.commit()
    print("[RESET] agg_synergy_role cleared + backfill_done cleared for job_id")


def _count_new_matches(con: sqlite3.Connection, job_id: str, patch: str) -> int:
    patch_pat = _patch_pat(patch)
    row = con.execute(
        """
        SELECT COUNT(*)
        FROM matches m
        WHERE m.patch LIKE ?
          AND NOT EXISTS (
            SELECT 1 FROM backfill_done d
            WHERE d.job_id = ? AND d.match_id = m.match_id
          )
        """,
        (patch_pat, job_id),
    ).fetchone()
    return int(row[0] or 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="lol_graph.db")
    ap.add_argument("--patch", default="ALL")
    ap.add_argument("--tier", default="ALL")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--commit_every", type=int, default=50, help="몇 매치마다 commit 할지")
    args = ap.parse_args()

    con = _connect(args.db)
    _ensure_tables(con)

    jobid = _job_id(args.patch, args.tier)

    if args.reset:
        _reset(con, jobid, args.patch, args.tier)

    new_cnt = _count_new_matches(con, jobid, args.patch)
    print(f"[INCR] new_matches={new_cnt} (job_id='{jobid}')")
    if new_cnt <= 0:
        print("OK build_synergy (nothing to do)")
        con.close()
        return

    patch_pat = _patch_pat(args.patch)
    ft = _force_tier(args.tier)

    mids = con.execute(
        """
        SELECT m.match_id, m.patch,
               (SELECT mt.tier_label FROM match_tier mt
                WHERE mt.match_id = m.match_id AND mt.method='median'
                LIMIT 1) AS mt_tier
        FROM matches m
        WHERE m.patch LIKE ?
          AND NOT EXISTS (
            SELECT 1 FROM backfill_done d
            WHERE d.job_id = ? AND d.match_id = m.match_id
          )
        ORDER BY m.game_creation ASC, m.match_id ASC
        """,
        (patch_pat, jobid),
    ).fetchall()

    agg = defaultdict(lambda: [0, 0])  # (patch,tier,my_role,ally_role,my_champ,ally_champ)->[games,wins]
    done_rows: List[Tuple[str, str]] = []
    processed = 0
    commit_every = max(1, int(args.commit_every))
    cur = con.cursor()

    for (mid, patch, mt_tier) in mids:
        tier = ft if ft is not None else mt_tier

        rows = cur.execute(
            "SELECT team_id, role, champ_id, win FROM participants WHERE match_id=?",
            (mid,),
        ).fetchall()

        teams = {}  # team_id -> list[(role, champ, win)]
        for team_id, role, champ_id, win in rows:
            role = (role or "").upper()
            if role not in ROLES:
                continue
            if not champ_id or int(champ_id) <= 0:
                continue
            teams.setdefault(int(team_id), []).append((role, int(champ_id), int(win or 0)))

        for _team_id, plist in teams.items():
            for my_role, my_champ, my_win in plist:
                for ally_role, ally_champ, _ in plist:
                    if my_role == ally_role and my_champ == ally_champ:
                        continue
                    key = (patch, tier, my_role, ally_role, my_champ, ally_champ)
                    agg[key][0] += 1
                    agg[key][1] += my_win

        done_rows.append((jobid, mid))
        processed += 1

        if processed % commit_every == 0:
            con.execute("BEGIN;")
            con.executemany(
                """
                INSERT INTO agg_synergy_role(patch, tier, my_role, ally_role, my_champ_id, ally_champ_id, games, wins)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(patch, tier, my_role, ally_role, my_champ_id, ally_champ_id) DO UPDATE SET
                  games = agg_synergy_role.games + excluded.games,
                  wins  = agg_synergy_role.wins  + excluded.wins
                """,
                [(k[0], k[1], k[2], k[3], k[4], k[5], v[0], v[1]) for k, v in agg.items()],
            )
            con.executemany(
                "INSERT OR IGNORE INTO backfill_done(job_id, match_id) VALUES(?,?)",
                done_rows,
            )
            con.commit()
            agg.clear()
            done_rows.clear()
            print(f"progress {processed}/{len(mids)}")

    if agg or done_rows:
        con.execute("BEGIN;")
        if agg:
            con.executemany(
                """
                INSERT INTO agg_synergy_role(patch, tier, my_role, ally_role, my_champ_id, ally_champ_id, games, wins)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(patch, tier, my_role, ally_role, my_champ_id, ally_champ_id) DO UPDATE SET
                  games = agg_synergy_role.games + excluded.games,
                  wins  = agg_synergy_role.wins  + excluded.wins
                """,
                [(k[0], k[1], k[2], k[3], k[4], k[5], v[0], v[1]) for k, v in agg.items()],
            )
        if done_rows:
            con.executemany(
                "INSERT OR IGNORE INTO backfill_done(job_id, match_id) VALUES(?,?)",
                done_rows,
            )
        con.commit()

    print("OK build_synergy")
    print("matches_processed=", processed)
    con.close()


if __name__ == "__main__":
    main()
