# backfill_rank.py
from __future__ import annotations

import argparse
import os
import time
import sqlite3
from pathlib import Path
from statistics import median
import requests
from dotenv import load_dotenv


# -----------------------------
# ENV loader (profile aware)
# -----------------------------
def load_env_for_profile(profile: str):
    here = Path(__file__).resolve().parent
    candidates = [
        here / f".env.{profile}",
        here / ".env",
        here / ".env.personal",
        here / ".env.public",
    ]
    loaded = []
    for p in candidates:
        if p.exists():
            load_dotenv(p, override=False)
            loaded.append(str(p))
    return loaded


# -----------------------------
# Riot endpoints (KR host)
# -----------------------------
KR_HOST = "https://kr.api.riotgames.com"

def riot_get(path: str, api_key: str, timeout: int = 15):
    url = KR_HOST + path
    return requests.get(url, headers={"X-Riot-Token": api_key}, timeout=timeout)


# -----------------------------
# tier score helpers
# -----------------------------
TIER_BASE = {
    "IRON": 1,
    "BRONZE": 2,
    "SILVER": 3,
    "GOLD": 4,
    "PLATINUM": 5,
    "EMERALD": 6,
    "DIAMOND": 7,
    "MASTER": 8,
    "GRANDMASTER": 9,
    "CHALLENGER": 10,
}
DIV_OFF = {"IV": 0.00, "III": 0.25, "II": 0.50, "I": 0.75}

def tier_to_score(tier: str | None, division: str | None) -> float | None:
    if not tier:
        return None
    t = tier.strip().upper()
    if t in ("UNRANKED", "NONE", ""):
        return None
    base = TIER_BASE.get(t)
    if base is None:
        return None
    if t in ("MASTER", "GRANDMASTER", "CHALLENGER"):
        return float(base)
    d = (division or "").strip().upper()
    return float(base) + float(DIV_OFF.get(d, 0.0))

def score_to_tier_label(score: float | None) -> str | None:
    if score is None:
        return None
    k = int(score)
    inv = {v: kk for kk, v in TIER_BASE.items()}
    return inv.get(k)


# -----------------------------
# pick puuids to process (IMPORTANT)
# -----------------------------
def pick_target_puuids(con: sqlite3.Connection, max_players: int, debug: bool) -> list[str]:
    """
    핵심: players LIMIT N이 아니라,
    1) match_tier가 아직 비어있는 match들의 participants puuid를 우선
    2) 그 안에서도 '등장 횟수 많은 puuid'부터
    3) 그래도 부족하면 players에서 tier NULL인 puuid로 보충
    """
    # 0) players가 비어있으면 participants로 안전하게 채움
    con.execute("""
        INSERT OR IGNORE INTO players(puuid, summoner_id, tier, division, league_points, last_rank_update)
        SELECT DISTINCT puuid, NULL, NULL, NULL, NULL, NULL FROM participants
    """)
    con.commit()

    # 1) match_tier가 비어있는 match들의 puuid를 등장횟수 순으로
    rows = con.execute(
        """
        SELECT p.puuid, COUNT(*) AS c
        FROM participants p
        JOIN matches m ON m.match_id = p.match_id
        LEFT JOIN match_tier mt ON mt.match_id = m.match_id
        WHERE mt.tier_label IS NULL OR mt.tier_label=''
        GROUP BY p.puuid
        ORDER BY c DESC
        LIMIT ?
        """,
        (max_players,),
    ).fetchall()
    puuids = [r[0] for r in rows]

    if debug:
        print("[debug] puuids_from_missing_match_tier=", len(puuids))

    # 2) 부족하면 tier가 아직 NULL인 players에서 추가
    if len(puuids) < max_players:
        need = max_players - len(puuids)
        rows2 = con.execute(
            """
            SELECT puuid
            FROM players
            WHERE tier IS NULL OR tier=''
            LIMIT ?
            """,
            (need,),
        ).fetchall()
        puuids.extend([r[0] for r in rows2])

        if debug:
            print("[debug] puuids_filled_from_players_null=", len(rows2))

    # 중복 제거(순서 유지)
    seen = set()
    uniq = []
    for p in puuids:
        if p and p not in seen:
            seen.add(p)
            uniq.append(p)

    return uniq[:max_players]


# -----------------------------
# main
# -----------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--max_players", type=int, default=400)
    ap.add_argument("--min_known", type=int, default=6)
    ap.add_argument("--sleep", type=float, default=0.18)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    profile = (os.getenv("APP_PROFILE") or "personal").strip()
    loaded = load_env_for_profile(profile)

    api_key = (os.getenv("RIOT_API_KEY") or "").strip()
    print(f"PROFILE {profile} KEY_HEAD {(api_key[:8] if api_key else '')}")
    if args.debug:
        print("DOTENV_LOADED", loaded)

    if not api_key:
        print("ERROR: RIOT_API_KEY is empty. (.env.* 로딩/APP_PROFILE 확인)")
        return

    con = sqlite3.connect(args.db, check_same_thread=False)
    con.row_factory = sqlite3.Row

    puuids = pick_target_puuids(con, args.max_players, args.debug)

    if args.debug:
        print("[debug] players_count_in_db=", con.execute("SELECT COUNT(*) FROM players").fetchone()[0])
        print("[debug] puuids_to_process=", len(puuids))
        if puuids:
            print("[debug] first_puuid=", puuids[0])

    # -------------------------
    # 1) players 티어 채우기 (League-V4 by-puuid)
    # -------------------------
    updated = 0
    status_hist: dict[int, int] = {}
    puuid_ok = 0
    now_ts = int(time.time())

    for puuid in puuids:
        path = f"/lol/league/v4/entries/by-puuid/{puuid}"
        r = riot_get(path, api_key)

        status_hist[r.status_code] = status_hist.get(r.status_code, 0) + 1

        if r.status_code == 429:
            ra = r.headers.get("Retry-After")
            wait = float(ra) if ra else 2.0
            if args.debug:
                print(f"[debug] 429 rate limit. sleep {wait}s")
            time.sleep(wait)
            continue

        if r.status_code in (401, 403):
            print(f"[debug] league fail status={r.status_code} body_head={r.text[:200]}")
            break

        if r.status_code != 200:
            if args.debug:
                print(f"[debug] league fail status={r.status_code} head={r.text[:200]}")
            time.sleep(args.sleep)
            continue

        puuid_ok += 1
        try:
            entries = r.json()
        except Exception:
            entries = []

        solo = None
        for e in entries or []:
            if (e.get("queueType") or "") == "RANKED_SOLO_5x5":
                solo = e
                break

        if solo:
            tier = (solo.get("tier") or "").upper()
            div = (solo.get("rank") or "").upper()
            lp = int(solo.get("leaguePoints") or 0)
        else:
            tier, div, lp = None, None, None

        con.execute(
            """
            UPDATE players
            SET tier=?, division=?, league_points=?, last_rank_update=?
            WHERE puuid=?
            """,
            (tier, div, lp, now_ts, puuid),
        )
        updated += 1
        time.sleep(args.sleep)

    con.commit()

    with_tier = con.execute("SELECT COUNT(*) FROM players WHERE tier IS NOT NULL AND tier!=''").fetchone()[0]
    print(f"[players] puuid_ok={puuid_ok}")
    print(f"[players] updated={updated}, with_tier={with_tier} status_hist={status_hist}")

    # -------------------------
    # 2) match_participant_rank 갱신
    # -------------------------
    rows = con.execute("""
        SELECT p.match_id, p.puuid, pl.tier, pl.division, pl.league_points
        FROM participants p
        JOIN players pl ON pl.puuid = p.puuid
    """).fetchall()

    con.executemany(
        """
        INSERT INTO match_participant_rank(match_id, puuid, as_of_ts, tier, division, league_points)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(match_id, puuid) DO UPDATE SET
          as_of_ts=excluded.as_of_ts,
          tier=excluded.tier,
          division=excluded.division,
          league_points=excluded.league_points
        """,
        [(r["match_id"], r["puuid"], now_ts, r["tier"], r["division"], r["league_points"]) for r in rows],
    )
    con.commit()

    # -------------------------
    # 3) match_tier 계산: match_participant_rank 기반 median
    #    (tier_label이 비어있는 match만 대상)
    # -------------------------
    targets = [r[0] for r in con.execute("""
        SELECT m.match_id
        FROM matches m
        LEFT JOIN match_tier mt ON mt.match_id = m.match_id
        WHERE mt.tier_label IS NULL OR mt.tier_label=''
    """).fetchall()]

    if args.debug:
        print("[debug] match_tier_targets=", len(targets))

    inserted = 0
    for mid in targets:
        pr = con.execute("""
            SELECT tier, division FROM match_participant_rank
            WHERE match_id=?
        """, (mid,)).fetchall()

        scores = []
        for r in pr:
            sc = tier_to_score(r["tier"], r["division"])
            if sc is not None:
                scores.append(sc)

        known_cnt = len(scores)
        if known_cnt < args.min_known:
            continue

        med = float(median(scores))
        label = score_to_tier_label(med)

        patch = con.execute("SELECT patch FROM matches WHERE match_id=?", (mid,)).fetchone()
        patch = patch[0] if patch else None

        con.execute(
            """
            INSERT INTO match_tier(match_id, patch, method, tier_label, tier_score, known_cnt, as_of_ts)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(match_id) DO UPDATE SET
              patch=excluded.patch,
              method=excluded.method,
              tier_label=excluded.tier_label,
              tier_score=excluded.tier_score,
              known_cnt=excluded.known_cnt,
              as_of_ts=excluded.as_of_ts
            """,
            (mid, patch, "median_current", label, med, known_cnt, now_ts),
        )
        inserted += 1

    con.commit()
    print(f"[match_tier] inserted_or_updated={inserted}")
    print("DONE")


if __name__ == "__main__":
    main()
