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
    if not db_roles and _table_exists(con, "participants"):
        for (x,) in con.execute("SELECT DISTINCT role FROM participants WHERE role IS NOT NULL"):
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
    return "(?='ALL' OR tier=? OR tier IS NULL)", (tier, tier)


def _role_total_games(con: sqlite3.Connection, role: str, patch: str, tier: str) -> int:
    if not _table_exists(con, "agg_champ_role"):
        return 0
    patch_sql, patch_args = _patch_condition(patch)
    tier_sql, tier_args = _tier_condition(tier)
    row = con.execute(
        f"""
        SELECT COALESCE(SUM(games),0)
        FROM agg_champ_role
        WHERE role=?
          AND {patch_sql}
          AND {tier_sql}
        """,
        (role, *patch_args, *tier_args),
    ).fetchone()
    return int(row[0] or 0) if row else 0


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
    min_games: int = 0,
    min_pick_rate: float = 0.005,  # 0.5% default
    top_n: int = 10,
    max_candidates: int = 400,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    ✅ 변경점:
    - champ_pool이 비어있으면 "전체 후보 모드"로 동작
    - min_pick_rate(기본 0.5%) 필터 지원
    - 반환값: (recs, debug_meta)
    """
    con = sqlite3.connect(db_path, check_same_thread=False)
    try:
        if not _table_exists(con, "agg_champ_role"):
            return [], {"reason": "missing table agg_champ_role"}

        my_role_db = _normalize_role_with_db(con, my_role)

        banset = set(int(x) for x in (bans or []))

        # 후보 모드 결정
        pool_raw = [int(x) for x in (champ_pool or []) if int(x) != 0]
        pool_raw = [x for x in pool_raw if x not in banset]
        use_all_candidates = (len(pool_raw) == 0)

        patch_sql, patch_args = _patch_condition(patch)
        tier_sql, tier_args = _tier_condition(tier)

        role_total = _role_total_games(con, my_role_db, patch, tier)
        # min_pick_rate를 games 기준으로 바꿔서 적용 (role_total=0이면 적용 불가)
        pr = float(min_pick_rate or 0.0)
        pr_games = 0
        if role_total > 0 and pr > 0.0:
            pr_games = int(math.ceil(role_total * pr))

        mg = int(min_games or 0)
        g_threshold = max(mg, pr_games)

        # ---- base candidates selection
        base_map: Dict[int, Dict[str, Any]] = {}

        if use_all_candidates:
            # 전체 후보: role/patch/tier에서 games>=threshold인 champ 전부
            q = f"""
              SELECT champ_id, games, wins
              FROM agg_champ_role
              WHERE role=?
                AND {patch_sql}
                AND {tier_sql}
                AND games >= ?
              ORDER BY games DESC
              LIMIT ?
            """
            rows = con.execute(
                q,
                (my_role_db, *patch_args, *tier_args, int(g_threshold), int(max_candidates)),
            ).fetchall()

            # role이 너무 빡세서 0이면 role조건 느슨하게(기존 로직 유지)
            if not rows:
                q2 = f"""
                  SELECT champ_id, SUM(games) AS games, SUM(wins) AS wins
                  FROM agg_champ_role
                  WHERE {patch_sql}
                    AND {tier_sql}
                  GROUP BY champ_id
                  HAVING games >= ?
                  ORDER BY games DESC
                  LIMIT ?
                """
                rows = con.execute(
                    q2,
                    (*patch_args, *tier_args, int(g_threshold), int(max_candidates)),
                ).fetchall()

        else:
            # 챔프폭 후보: IN(pool)
            pool = pool_raw
            q_base = f"""
              SELECT champ_id, games, wins
              FROM agg_champ_role
              WHERE role=?
                AND {patch_sql}
                AND {tier_sql}
                AND games >= ?
                AND champ_id IN ({",".join(["?"] * len(pool))})
            """
            args_base = (my_role_db, *patch_args, *tier_args, int(g_threshold), *pool)
            rows = con.execute(q_base, args_base).fetchall()

            # rows 0이면 role 느슨화
            if not rows:
                q_base2 = f"""
                  SELECT champ_id, SUM(games) AS games, SUM(wins) AS wins
                  FROM agg_champ_role
                  WHERE {patch_sql}
                    AND {tier_sql}
                    AND champ_id IN ({",".join(["?"] * len(pool))})
                  GROUP BY champ_id
                  HAVING games >= ?
                """
                args_base2 = (*patch_args, *tier_args, *pool, int(g_threshold))
                rows = con.execute(q_base2, args_base2).fetchall()

            # 최후: threshold 무시하고라도 보여주기
            if not rows:
                q_base3 = f"""
                  SELECT champ_id, SUM(games) AS games, SUM(wins) AS wins
                  FROM agg_champ_role
                  WHERE {patch_sql}
                    AND {tier_sql}
                    AND champ_id IN ({",".join(["?"] * len(pool))})
                  GROUP BY champ_id
                """
                args_base3 = (*patch_args, *tier_args, *pool)
                rows = con.execute(q_base3, args_base3).fetchall()

        if not rows:
            return [], {
                "reason": "no base rows",
                "use_all_candidates": use_all_candidates,
                "role_total": role_total,
                "min_games": mg,
                "min_pick_rate": pr,
                "games_threshold": g_threshold,
            }

        for cid, g, w in rows:
            cid = int(cid)
            if cid in banset:
                continue
            g = int(g or 0)
            w = int(w or 0)
            if g <= 0:
                continue
            wr = 100.0 * (w / g)
            lb = 100.0 * _wilson_lower_bound(w, g)
            pick_rate = (g / role_total) if role_total > 0 else 0.0
            base_map[cid] = {
                "games": g,
                "wins": w,
                "base_wr": wr,
                "base_lb": lb,
                "pick_rate": pick_rate,
            }

        if not base_map:
            return [], {"reason": "empty base_map after bans filter"}

        # ---- synergy: agg_synergy_role가 있으면 반영(없으면 0)
        synergy_delta: Dict[int, float] = defaultdict(float)
        synergy_samples: Dict[int, int] = defaultdict(int)

        if _table_exists(con, "agg_synergy_role"):
            sc = _cols(con, "agg_synergy_role")
            my_role_col = "my_role" if "my_role" in sc else ("role" if "role" in sc else None)
            ally_role_col = "ally_role" if "ally_role" in sc else ("other_role" if "other_role" in sc else None)
            my_c_col = "my_champ_id" if "my_champ_id" in sc else ("champ_id" if "champ_id" in sc else None)
            ally_c_col = "ally_champ_id" if "ally_champ_id" in sc else ("other_champ_id" if "other_champ_id" in sc else None)

            if my_role_col and my_c_col and ally_c_col:
                for ally_role, ally_list in (ally_picks_by_role or {}).items():
                    ally_role_u = _normalize_role_with_db(con, ally_role)
                    for ally_cid in ally_list or []:
                        ally_cid = int(ally_cid)
                        q_syn = f"""
                          SELECT {my_c_col}, games, wins
                          FROM agg_synergy_role
                          WHERE {my_role_col}=? AND {ally_c_col}=?
                            AND {patch_sql} AND {tier_sql}
                        """
                        syn_args = [my_role_db, ally_cid, *patch_args, *tier_args]
                        if ally_role_col:
                            q_syn = q_syn.replace("WHERE", "WHERE " + ally_role_col + "=? AND ", 1)
                            syn_args = [ally_role_u] + syn_args

                        for my_cid, g2, w2 in con.execute(q_syn, tuple(syn_args)).fetchall():
                            my_cid = int(my_cid)
                            if my_cid not in base_map:
                                continue
                            g2 = int(g2 or 0)
                            w2 = int(w2 or 0)
                            if g2 <= 0:
                                continue
                            wr2 = 100.0 * (w2 / g2)
                            synergy_delta[my_cid] += (wr2 - base_map[my_cid]["base_wr"])
                            synergy_samples[my_cid] += g2

        # ---- counter: agg_matchup_role가 있으면 반영(없으면 0)
        counter_delta: Dict[int, float] = defaultdict(float)
        counter_samples: Dict[int, int] = defaultdict(int)

        if _table_exists(con, "agg_matchup_role"):
            mc = _cols(con, "agg_matchup_role")
            my_role_col = "my_role" if "my_role" in mc else ("role" if "role" in mc else None)
            enemy_role_col = "enemy_role" if "enemy_role" in mc else None
            my_c_col = "my_champ_id" if "my_champ_id" in mc else ("champ_id" if "champ_id" in mc else None)
            e_c_col = "enemy_champ_id" if "enemy_champ_id" in mc else ("other_champ_id" if "other_champ_id" in mc else None)

            if my_role_col and my_c_col and e_c_col:
                dist = champ_role_distribution(con, patch, tier)
                guessed = guess_enemy_roles([int(x) for x in (enemy_picks or [])], dist)

                for e_cid in (enemy_picks or []):
                    e_cid = int(e_cid)
                    e_role = guessed.get(e_cid, "UNKNOWN")
                    if enemy_role_col and e_role != "UNKNOWN":
                        q_ct = f"""
                          SELECT {my_c_col}, games, wins
                          FROM agg_matchup_role
                          WHERE {my_role_col}=? AND {enemy_role_col}=? AND {e_c_col}=?
                            AND {patch_sql} AND {tier_sql}
                        """
                        args_ct = (my_role_db, e_role, e_cid, *patch_args, *tier_args)
                    else:
                        q_ct = f"""
                          SELECT {my_c_col}, games, wins
                          FROM agg_matchup_role
                          WHERE {my_role_col}=? AND {e_c_col}=?
                            AND {patch_sql} AND {tier_sql}
                        """
                        args_ct = (my_role_db, e_cid, *patch_args, *tier_args)

                    for my_cid, g2, w2 in con.execute(q_ct, args_ct).fetchall():
                        my_cid = int(my_cid)
                        if my_cid not in base_map:
                            continue
                        g2 = int(g2 or 0)
                        w2 = int(w2 or 0)
                        if g2 <= 0:
                            continue
                        wr2 = 100.0 * (w2 / g2)
                        counter_delta[my_cid] += (wr2 - base_map[my_cid]["base_wr"])
                        counter_samples[my_cid] += g2

        # ---- assemble
        recs: List[Dict[str, Any]] = []
        for cid, b in base_map.items():
            syn = float(synergy_delta.get(cid, 0.0))
            ctd = float(counter_delta.get(cid, 0.0))
            final = float(b["base_lb"] + syn + ctd)

            recs.append(
                {
                    "champ_id": int(cid),
                    "final_score": round(final, 2),
                    "base_wr": round(float(b["base_wr"]), 2),
                    "base_lb": round(float(b["base_lb"]), 2),
                    "games": int(b["games"]),
                    "pick_rate": round(float(b.get("pick_rate", 0.0)) * 100.0, 3),  # %
                    "counter_delta": round(ctd, 2),
                    "counter_samples": int(counter_samples.get(cid, 0)),
                    "synergy_delta": round(syn, 2),
                    "synergy_samples": int(synergy_samples.get(cid, 0)),
                }
            )

        recs.sort(key=lambda x: (x["final_score"], x["games"]), reverse=True)

        meta = {
            "use_all_candidates": use_all_candidates,
            "role_total_games": role_total,
            "min_games": mg,
            "min_pick_rate": pr,
            "games_threshold": g_threshold,
            "candidate_count": len(base_map),
            "max_candidates": int(max_candidates),
        }
        return recs[: int(top_n)], meta

    finally:
        try:
            con.close()
        except Exception:
            pass
