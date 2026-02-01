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

    db_roles = set()
    if _table_exists(con, "agg_champ_role"):
        for row in con.execute("SELECT DISTINCT role FROM agg_champ_role WHERE role IS NOT NULL"):
            x = row[0] if row else None
            if x:
                db_roles.add(str(x).upper())
    if not db_roles and _table_exists(con, "participants"):
        for row in con.execute("SELECT DISTINCT role FROM participants WHERE role IS NOT NULL"):
            x = row[0] if row else None
            if x:
                db_roles.add(str(x).upper())

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

    if not db_roles or r in db_roles:
        return r

    for cand in syn.get(r, [r]):
        if cand in db_roles:
            return cand

    if r in syn:
        for cand in syn[r]:
            if cand in ROLES:
                return cand

    return r


def _patch_condition(patch: str) -> Tuple[str, Tuple[Any, ...]]:
    # patch='ALL'이면 전체 허용
    return "(?='ALL' OR patch=?)", (patch, patch)


def _tier_condition(tier: str) -> Tuple[str, Tuple[Any, ...]]:
    return "(?='ALL' OR tier=? OR tier IS NULL)", (tier, tier)


# -------------------------
# patch helpers
# -------------------------
def get_latest_patch(con: sqlite3.Connection) -> Optional[str]:
    if not _table_exists(con, "matches"):
        return None
    row = con.execute(
        "SELECT patch FROM matches WHERE patch IS NOT NULL AND patch!='' ORDER BY game_creation DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def get_available_patches(con: sqlite3.Connection) -> List[str]:
    if not _table_exists(con, "matches"):
        return []
    rows = con.execute(
        "SELECT DISTINCT patch FROM matches WHERE patch IS NOT NULL AND patch!='' ORDER BY patch"
    ).fetchall()
    return [r[0] for r in rows if r and r[0]]


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

    # ✅ 이미 SUM/GROUP BY라서 ALL에서도 안전
    q = f"""
      SELECT champ_id, role, SUM(games)
      FROM agg_champ_role
      WHERE {patch_sql} AND {tier_sql}
      GROUP BY champ_id, role
    """
    for row in con.execute(q, (*patch_args, *tier_args)).fetchall():
        cid = row[0]
        role = row[1]
        g = row[2] if len(row) > 2 else 0
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


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


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
    min_games: int = 30,              # (호환용) 남겨둠
    min_pick_rate: float = 0.005,     # 기본 0.5%
    use_champ_pool: bool = True,      # True면 champ_pool 후보만 / False면 전체 후보
    max_candidates: int = 400,        # 전체 후보일 때 후보 상한
    top_n: int = 10,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    return: (recs, meta)
    meta.reason: 디버깅용
    """
    con = sqlite3.connect(db_path, check_same_thread=False)
    try:
        if not _table_exists(con, "agg_champ_role"):
            return [], {"reason": "missing table agg_champ_role"}

        my_role_db = _normalize_role_with_db(con, my_role)
        banset = set(int(x) for x in (bans or []))

        patch_sql, patch_args = _patch_condition(patch)
        tier_sql, tier_args = _tier_condition(tier)

        # -------------------------
        # 1) candidate set 만들기
        # -------------------------
        candidates: List[int] = []

        if use_champ_pool:
            pool = [int(x) for x in (champ_pool or []) if int(x) != 0]
            pool = [x for x in pool if x not in banset]
            if not pool:
                return [], {"reason": "champ_pool empty(after bans) while use_champ_pool=true"}
            candidates = pool
        else:
            # 전체 후보: pick_rate >= min_pick_rate
            # pick_rate = champ_games / total_games_for_role
            q_total = f"""
              SELECT SUM(games)
              FROM agg_champ_role
              WHERE role=?
                AND {patch_sql}
                AND {tier_sql}
            """
            total_row = con.execute(q_total, (my_role_db, *patch_args, *tier_args)).fetchone()
            total_games = int((total_row[0] if total_row else 0) or 0)
            if total_games <= 0:
                return [], {"reason": "total_games_for_role is 0 (no data for role/patch/tier)"}

            q_cand = f"""
              SELECT champ_id, SUM(games) AS g
              FROM agg_champ_role
              WHERE role=?
                AND {patch_sql}
                AND {tier_sql}
              GROUP BY champ_id
              ORDER BY g DESC
              LIMIT ?
            """
            rows = con.execute(q_cand, (my_role_db, *patch_args, *tier_args, int(max_candidates))).fetchall()
            for row in rows:
                cid = row[0]
                g = row[1] if len(row) > 1 else 0
                if cid is None:
                    continue
                cid = int(cid)
                if cid in banset:
                    continue
                g = int(g or 0)
                pr = (g / total_games) if total_games > 0 else 0.0
                if pr >= float(min_pick_rate):
                    candidates.append(cid)

            if not candidates:
                return [], {"reason": "no candidates after pick_rate filter"}

        # -------------------------
        # 2) base: ✅ ALL에서도 안전하게 SUM/GROUP BY로 가져오기
        # -------------------------
        q_base = f"""
          SELECT champ_id, SUM(games) AS games, SUM(wins) AS wins
          FROM agg_champ_role
          WHERE role=?
            AND {patch_sql}
            AND {tier_sql}
            AND champ_id IN ({",".join(["?"] * len(candidates))})
          GROUP BY champ_id
        """
        rows = con.execute(q_base, (my_role_db, *patch_args, *tier_args, *candidates)).fetchall()

        # role 데이터가 너무 없으면 role 없이 한번 더(안전장치)
        if not rows:
            q_base2 = f"""
              SELECT champ_id, SUM(games) AS games, SUM(wins) AS wins
              FROM agg_champ_role
              WHERE {patch_sql}
                AND {tier_sql}
                AND champ_id IN ({",".join(["?"] * len(candidates))})
              GROUP BY champ_id
            """
            rows = con.execute(q_base2, (*patch_args, *tier_args, *candidates)).fetchall()

        if not rows:
            return [], {"reason": "no base rows"}

        base_map: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            cid = int(row[0])
            g = int((row[1] if len(row) > 1 else 0) or 0)
            w = int((row[2] if len(row) > 2 else 0) or 0)
            if g <= 0:
                continue
            wr = 100.0 * (w / g)
            lb = 100.0 * _wilson_lower_bound(w, g)
            base_map[cid] = {"games": g, "wins": w, "base_wr": wr, "base_lb": lb}

        if not base_map:
            return [], {"reason": "base_map empty"}

        # -------------------------
        # 3) synergy: ✅ SUM/GROUP BY로 "패치/티어 행 여러개" 누적 폭발 방지
        # -------------------------
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
                          SELECT {my_c_col} AS my_cid, SUM(games) AS games, SUM(wins) AS wins
                          FROM agg_synergy_role
                          WHERE {my_role_col}=? AND {ally_c_col}=?
                            AND {patch_sql} AND {tier_sql}
                          GROUP BY {my_c_col}
                        """
                        syn_args: List[Any] = [my_role_db, ally_cid, *patch_args, *tier_args]
                        if ally_role_col:
                            q_syn = q_syn.replace("WHERE", "WHERE " + ally_role_col + "=? AND ", 1)
                            syn_args = [ally_role_u] + syn_args

                        for row in con.execute(q_syn, tuple(syn_args)).fetchall():
                            my_cid = int(row[0])
                            g = int((row[1] if len(row) > 1 else 0) or 0)
                            w = int((row[2] if len(row) > 2 else 0) or 0)
                            if my_cid not in base_map or g <= 0:
                                continue
                            wr = 100.0 * (w / g)
                            delta = wr - base_map[my_cid]["base_wr"]
                            # 폭발 방지 2차 안전장치(개별 조합 델타를 너무 크게 못 가게)
                            delta = _clamp(delta, -20.0, 20.0)

                            synergy_delta[my_cid] += delta
                            synergy_samples[my_cid] += g

        # -------------------------
        # 4) counter: ✅ SUM/GROUP BY로 폭발 방지
        # -------------------------
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
                          SELECT {my_c_col} AS my_cid, SUM(games) AS games, SUM(wins) AS wins
                          FROM agg_matchup_role
                          WHERE {my_role_col}=? AND {enemy_role_col}=? AND {e_c_col}=?
                            AND {patch_sql} AND {tier_sql}
                          GROUP BY {my_c_col}
                        """
                        args_ct: Tuple[Any, ...] = (my_role_db, e_role, e_cid, *patch_args, *tier_args)
                    else:
                        q_ct = f"""
                          SELECT {my_c_col} AS my_cid, SUM(games) AS games, SUM(wins) AS wins
                          FROM agg_matchup_role
                          WHERE {my_role_col}=? AND {e_c_col}=?
                            AND {patch_sql} AND {tier_sql}
                          GROUP BY {my_c_col}
                        """
                        args_ct = (my_role_db, e_cid, *patch_args, *tier_args)

                    for row in con.execute(q_ct, args_ct).fetchall():
                        my_cid = int(row[0])
                        g = int((row[1] if len(row) > 1 else 0) or 0)
                        w = int((row[2] if len(row) > 2 else 0) or 0)
                        if my_cid not in base_map or g <= 0:
                            continue
                        wr = 100.0 * (w / g)
                        delta = wr - base_map[my_cid]["base_wr"]
                        delta = _clamp(delta, -20.0, 20.0)

                        counter_delta[my_cid] += delta
                        counter_samples[my_cid] += g

        # -------------------------
        # 5) assemble
        # -------------------------
        recs: List[Dict[str, Any]] = []
        for cid, b in base_map.items():
            syn = float(synergy_delta.get(cid, 0.0))
            ctd = float(counter_delta.get(cid, 0.0))

            # 총합도 안전장치(너무 과하게 못 가게)
            syn = _clamp(syn, -30.0, 30.0)
            ctd = _clamp(ctd, -30.0, 30.0)

            final = float(b["base_lb"] + syn + ctd)

            recs.append(
                {
                    "champ_id": int(cid),
                    "final_score": round(final, 2),
                    "base_wr": round(float(b["base_wr"]), 2),
                    "base_lb": round(float(b["base_lb"]), 2),
                    "games": int(b["games"]),
                    "counter_delta": round(ctd, 2),
                    "counter_samples": int(counter_samples.get(cid, 0)),
                    "synergy_delta": round(syn, 2),
                    "synergy_samples": int(synergy_samples.get(cid, 0)),
                }
            )

        recs.sort(key=lambda x: (x["final_score"], x["games"]), reverse=True)
        return recs[: int(top_n)], {"reason": "ok"}
    finally:
        try:
            con.close()
        except Exception:
            pass
