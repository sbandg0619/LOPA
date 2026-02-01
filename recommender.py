# recommender.py
from __future__ import annotations

import sqlite3
import math
from collections import defaultdict
from typing import Dict, List, Tuple, Optional, Any


ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]


# -------------------------
# utilities
# -------------------------
def _wilson_lower_bound(wins: int, n: int, z: float = 1.96) -> float:
    """Wilson score lower bound for a Bernoulli parameter (as fraction 0..1)."""
    if n <= 0:
        return 0.0
    phat = wins / n
    denom = 1.0 + (z * z) / n
    center = phat + (z * z) / (2.0 * n)
    margin = z * math.sqrt((phat * (1 - phat) + (z * z) / (4.0 * n)) / n)
    return max(0.0, (center - margin) / denom)


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _cols(con: sqlite3.Connection, table: str) -> List[str]:
    try:
        return [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
    except Exception:
        return []


def _normalize_role_with_db(con: sqlite3.Connection, role: str) -> str:
    """
    입력 role을 DB에 실제 존재하는 role 값으로 최대한 맞춰줌.
    - DB(agg_champ_role.role)에 있는 distinct 값을 보고 매칭
    """
    r = (role or "").upper().strip()
    if not r:
        return "MIDDLE"

    # DB에 존재하는 role 값 수집
    db_roles = set()
    if _table_exists(con, "agg_champ_role"):
        for (x,) in con.execute("SELECT DISTINCT role FROM agg_champ_role WHERE role IS NOT NULL"):
            if x:
                db_roles.add(str(x).upper())

    # 후보 동의어
    syn = {
        "MIDDLE": ["MIDDLE", "MID"],
        "MID": ["MID", "MIDDLE"],
        "BOTTOM": ["BOTTOM", "BOT", "ADC"],
        "BOT": ["BOT", "BOTTOM", "ADC"],
        "ADC": ["ADC", "BOTTOM", "BOT"],
        "UTILITY": ["UTILITY", "SUPPORT", "SUP"],
        "SUPPORT": ["SUPPORT", "UTILITY", "SUP"],
        "SUP": ["SUP", "UTILITY", "SUPPORT"],
        "JUNGLE": ["JUNGLE", "JG"],
        "JG": ["JG", "JUNGLE"],
        "TOP": ["TOP"],
    }

    # 1) 그대로 있으면 OK
    if not db_roles or r in db_roles:
        return r

    # 2) 동의어 중 DB에 있는 걸로
    for cand in syn.get(r, [r]):
        if cand in db_roles:
            return cand

    # 3) 표준 ROLES에서 가장 그럴싸한 값
    if r in syn:
        for cand in syn[r]:
            if cand in ROLES:
                return cand

    return r


def _patch_condition(patch: str) -> Tuple[str, Tuple[Any, ...]]:
    """
    patch='ALL'이면 조건을 안 거는 형태로 만들기 위해
    WHERE ( ?='ALL' OR patch=? )
    """
    return "(?='ALL' OR patch=?)", (patch, patch)


def _tier_condition(tier: str) -> Tuple[str, Tuple[Any, ...]]:
    # tier가 NULL인 데이터도 허용(기존 로직 유지)
    return "(?='ALL' OR tier=? OR tier IS NULL)", (tier, tier)


# -------------------------
# patch helpers
# -------------------------
def get_latest_patch(con: sqlite3.Connection) -> Optional[str]:
    row = con.execute(
        "SELECT patch FROM matches WHERE patch IS NOT NULL AND patch!='' ORDER BY game_creation DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def get_available_patches(con: sqlite3.Connection) -> List[str]:
    rows = con.execute(
        "SELECT DISTINCT patch FROM matches WHERE patch IS NOT NULL AND patch!='' ORDER BY patch"
    ).fetchall()
    return [r[0] for r in rows]


# -------------------------
# enemy role guess (optional)
# -------------------------
def champ_role_distribution(con: sqlite3.Connection, patch: str, tier: str) -> Dict[int, Dict[str, int]]:
    """
    champ_id -> {role -> games}
    """
    dist: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    if not _table_exists(con, "agg_champ_role"):
        return dist

    patch_sql, patch_args = _patch_condition(patch)
    tier_sql, tier_args = _tier_condition(tier)

    q = f"""
      SELECT champ_id, role, SUM(games)
      FROM agg_champ_role
      WHERE {patch_sql} AND {tier_sql}
      GROUP BY champ_id, role
    """
    for cid, role, g in con.execute(q, (*patch_args, *tier_args)).fetchall():
        if cid is None or role is None:
            continue
        dist[int(cid)][str(role).upper()] += int(g or 0)
    return dist


def guess_enemy_roles(enemy_ids: List[int], dist: Dict[int, Dict[str, int]]) -> Dict[int, str]:
    out: Dict[int, str] = {}
    for cid in enemy_ids or []:
        m = dist.get(int(cid)) or {}
        if not m:
            out[int(cid)] = "UNKNOWN"
            continue
        out[int(cid)] = max(m.items(), key=lambda kv: kv[1])[0]
    return out


# -------------------------
# core recommender
# -------------------------
def recommend_champions(
    db_path: str,
    patch: str,
    tier: str,
    my_role: str,
    champ_pool: List[int],
    bans: List[int],
    ally_picks_by_role: Dict[str, List[int]],
    enemy_picks: List[int],
    min_games: int = 30,
    top_n: int = 10,
    # 아래는 네가 이미 API에서 쓰고 있는 값(응답 meta에 보이던 값들)
    min_pick_rate: float = 0.005,   # 0.5% 기본
    max_candidates: int = 400,
    use_pool: bool = True,
) -> List[Dict[str, Any]]:
    """
    - patch/tier가 ALL일 때 patch/tier별 행이 중복 누적되며 점수가 폭발하던 문제를 해결:
      base/synergy/counter 모두 SUM + GROUP BY로 "통합 1행"으로 만든 뒤 계산.
    - synergy/counter는 (wr - base_wr)를 games로 가중평균하여 스케일을 안정화.
    """

    con = sqlite3.connect(db_path, check_same_thread=False)
    try:
        if not _table_exists(con, "agg_champ_role"):
            return []

        my_role_db = _normalize_role_with_db(con, my_role)

        patch_sql, patch_args = _patch_condition(patch)
        tier_sql, tier_args = _tier_condition(tier)

        banset = set(int(x) for x in (bans or []))

        # -------------------------
        # 후보군(candidates) 결정
        # -------------------------
        candidates: List[int] = []

        if use_pool:
            pool = [int(x) for x in (champ_pool or [])]
            pool = [x for x in pool if x != 0 and x not in banset]
            # pool 모드면 비어있으면 추천 불가
            if not pool:
                return []
            candidates = pool[:]
        else:
            # 전체 후보 모드: my_role 기준으로 픽률(min_pick_rate) 이상인 챔프를 candidates로 구성
            # total_role_games를 먼저 구해 픽률 계산
            q_total = f"""
              SELECT COALESCE(SUM(games), 0)
              FROM agg_champ_role
              WHERE role=?
                AND {patch_sql}
                AND {tier_sql}
            """
            total_role_games = int(con.execute(q_total, (my_role_db, *patch_args, *tier_args)).fetchone()[0] or 0)

            if total_role_games <= 0:
                # role 데이터가 거의 없으면 role 조건을 풀어 전체 기준으로라도 후보를 구성
                q_total2 = f"""
                  SELECT COALESCE(SUM(games), 0)
                  FROM agg_champ_role
                  WHERE {patch_sql}
                    AND {tier_sql}
                """
                total_role_games = int(con.execute(q_total2, (*patch_args, *tier_args)).fetchone()[0] or 0)

                q_cand2 = f"""
                  SELECT champ_id, COALESCE(SUM(games),0) AS g
                  FROM agg_champ_role
                  WHERE {patch_sql}
                    AND {tier_sql}
                  GROUP BY champ_id
                  ORDER BY g DESC
                  LIMIT ?
                """
                rows = con.execute(q_cand2, (*patch_args, *tier_args, int(max_candidates))).fetchall()
            else:
                # role 기준 후보
                q_cand = f"""
                  SELECT champ_id, COALESCE(SUM(games),0) AS g
                  FROM agg_champ_role
                  WHERE role=?
                    AND {patch_sql}
                    AND {tier_sql}
                  GROUP BY champ_id
                  ORDER BY g DESC
                  LIMIT ?
                """
                rows = con.execute(q_cand, (my_role_db, *patch_args, *tier_args, int(max_candidates))).fetchall()

            for cid, g in rows:
                cid = int(cid)
                g = int(g or 0)
                if cid == 0 or cid in banset:
                    continue
                # 픽률 필터: total_role_games가 0이면 그냥 통과
                if total_role_games > 0:
                    pr = g / float(total_role_games)
                    if pr < float(min_pick_rate):
                        continue
                candidates.append(cid)

            if not candidates:
                return []

        # -------------------------
        # base: 기본 승률/하한 (항상 GROUP BY로 통합)
        # -------------------------
        placeholders = ",".join(["?"] * len(candidates))

        q_base = f"""
          SELECT champ_id, COALESCE(SUM(games),0) AS games, COALESCE(SUM(wins),0) AS wins
          FROM agg_champ_role
          WHERE role=?
            AND {patch_sql}
            AND {tier_sql}
            AND champ_id IN ({placeholders})
          GROUP BY champ_id
          HAVING games >= ?
        """
        args_base = (my_role_db, *patch_args, *tier_args, *candidates, int(min_games))
        rows = con.execute(q_base, args_base).fetchall()

        # role별 데이터가 없으면 role 조건을 한 번 풀어보기(기존 안정장치 유지)
        if not rows:
            q_base2 = f"""
              SELECT champ_id, COALESCE(SUM(games),0) AS games, COALESCE(SUM(wins),0) AS wins
              FROM agg_champ_role
              WHERE {patch_sql}
                AND {tier_sql}
                AND champ_id IN ({placeholders})
              GROUP BY champ_id
              HAVING games >= ?
            """
            args_base2 = (*patch_args, *tier_args, *candidates, int(min_games))
            rows = con.execute(q_base2, args_base2).fetchall()

        # 최후: min_games를 무시하고라도 base를 구성(기존 안정장치 유지)
        if not rows:
            q_base3 = f"""
              SELECT champ_id, COALESCE(SUM(games),0) AS games, COALESCE(SUM(wins),0) AS wins
              FROM agg_champ_role
              WHERE {patch_sql}
                AND {tier_sql}
                AND champ_id IN ({placeholders})
              GROUP BY champ_id
            """
            args_base3 = (*patch_args, *tier_args, *candidates)
            rows = con.execute(q_base3, args_base3).fetchall()

        if not rows:
            return []

        base_map: Dict[int, Dict[str, Any]] = {}
        for cid, g, w in rows:
            cid = int(cid)
            g = int(g or 0)
            w = int(w or 0)
            if g <= 0:
                continue
            wr = 100.0 * (w / g)
            lb = 100.0 * _wilson_lower_bound(w, g)
            base_map[cid] = {"games": g, "wins": w, "base_wr": wr, "base_lb": lb}

        if not base_map:
            return []

        # -------------------------
        # synergy: 가중 평균으로 안정화 (SUM+GROUP BY로 통합)
        # -------------------------
        synergy_sum_wdelta: Dict[int, float] = defaultdict(float)  # sum((wr-base_wr) * games)
        synergy_sum_games: Dict[int, int] = defaultdict(int)       # sum(games)

        if _table_exists(con, "agg_synergy_role"):
            # 스키마 확정: patch,tier,my_role,ally_role,my_champ_id,ally_champ_id,games,wins
            for ally_role, ally_list in (ally_picks_by_role or {}).items():
                ally_role_u = _normalize_role_with_db(con, ally_role)
                for ally_cid in ally_list or []:
                    ally_cid = int(ally_cid)
                    if ally_cid == 0:
                        continue

                    q_syn = f"""
                      SELECT my_champ_id, COALESCE(SUM(games),0) AS g, COALESCE(SUM(wins),0) AS w
                      FROM agg_synergy_role
                      WHERE my_role=? AND ally_role=? AND ally_champ_id=?
                        AND {patch_sql} AND {tier_sql}
                      GROUP BY my_champ_id
                    """
                    syn_args = (my_role_db, ally_role_u, ally_cid, *patch_args, *tier_args)

                    for my_cid, g, w in con.execute(q_syn, syn_args).fetchall():
                        my_cid = int(my_cid)
                        if my_cid not in base_map:
                            continue
                        g = int(g or 0)
                        w = int(w or 0)
                        if g <= 0:
                            continue
                        wr = 100.0 * (w / g)
                        delta = wr - float(base_map[my_cid]["base_wr"])
                        synergy_sum_wdelta[my_cid] += delta * g
                        synergy_sum_games[my_cid] += g

        # -------------------------
        # counter: 가중 평균 + SUM+GROUP BY로 통합
        # -------------------------
        counter_sum_wdelta: Dict[int, float] = defaultdict(float)
        counter_sum_games: Dict[int, int] = defaultdict(int)

        if _table_exists(con, "agg_matchup_role"):
            # 스키마 확정: patch,tier,my_role,enemy_role,my_champ_id,enemy_champ_id,games,wins
            dist = champ_role_distribution(con, patch, tier)
            guessed = guess_enemy_roles([int(x) for x in (enemy_picks or [])], dist)

            for e_cid in (enemy_picks or []):
                e_cid = int(e_cid)
                if e_cid == 0:
                    continue
                e_role = guessed.get(e_cid, "UNKNOWN")

                if e_role != "UNKNOWN":
                    q_ct = f"""
                      SELECT my_champ_id, COALESCE(SUM(games),0) AS g, COALESCE(SUM(wins),0) AS w
                      FROM agg_matchup_role
                      WHERE my_role=? AND enemy_role=? AND enemy_champ_id=?
                        AND {patch_sql} AND {tier_sql}
                      GROUP BY my_champ_id
                    """
                    args_ct = (my_role_db, e_role, e_cid, *patch_args, *tier_args)
                else:
                    # enemy_role 추정 실패하면 enemy_role 조건을 빼고 집계
                    q_ct = f"""
                      SELECT my_champ_id, COALESCE(SUM(games),0) AS g, COALESCE(SUM(wins),0) AS w
                      FROM agg_matchup_role
                      WHERE my_role=? AND enemy_champ_id=?
                        AND {patch_sql} AND {tier_sql}
                      GROUP BY my_champ_id
                    """
                    args_ct = (my_role_db, e_cid, *patch_args, *tier_args)

                for my_cid, g, w in con.execute(q_ct, args_ct).fetchall():
                    my_cid = int(my_cid)
                    if my_cid not in base_map:
                        continue
                    g = int(g or 0)
                    w = int(w or 0)
                    if g <= 0:
                        continue
                    wr = 100.0 * (w / g)
                    delta = wr - float(base_map[my_cid]["base_wr"])
                    counter_sum_wdelta[my_cid] += delta * g
                    counter_sum_games[my_cid] += g

        # -------------------------
        # assemble
        # - synergy_delta/counter_delta는 "가중 평균 델타"로 안정화
        # - samples는 누적 games
        # -------------------------
        recs: List[Dict[str, Any]] = []
        for cid, b in base_map.items():
            cid = int(cid)

            syn_g = int(synergy_sum_games.get(cid, 0))
            ct_g = int(counter_sum_games.get(cid, 0))

            syn = float(synergy_sum_wdelta[cid] / syn_g) if syn_g > 0 else 0.0
            ctd = float(counter_sum_wdelta[cid] / ct_g) if ct_g > 0 else 0.0

            final = float(b["base_lb"] + syn + ctd)

            recs.append(
                {
                    "champ_id": cid,
                    "final_score": round(final, 2),
                    "base_wr": round(float(b["base_wr"]), 2),
                    "base_lb": round(float(b["base_lb"]), 2),
                    "games": int(b["games"]),
                    "counter_delta": round(ctd, 2),
                    "counter_samples": ct_g,
                    "synergy_delta": round(syn, 2),
                    "synergy_samples": syn_g,
                }
            )

        recs.sort(key=lambda x: (x["final_score"], x["games"]), reverse=True)
        return recs[: int(top_n)]
    finally:
        try:
            con.close()
        except Exception:
            pass
