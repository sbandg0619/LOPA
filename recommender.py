# recommender.py
from __future__ import annotations

import sqlite3
import math
from collections import defaultdict
from typing import Dict, List, Tuple, Optional, Any
from itertools import permutations

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
    return "(?='ALL' OR patch=?)", (patch, patch)


def _tier_condition(tier: str) -> Tuple[str, Tuple[Any, ...]]:
    return "(?='ALL' OR tier=? OR tier IS NULL)", (tier, tier)


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


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
# enemy role guess
# -------------------------
def champ_role_distribution(con: sqlite3.Connection, patch: str, tier: str) -> Dict[int, Dict[str, int]]:
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
    for row in con.execute(q, (*patch_args, *tier_args)).fetchall():
        cid = row[0]
        role = row[1]
        g = row[2] if len(row) > 2 else 0
        if cid is None or role is None:
            continue
        dist[int(cid)][str(role).upper()] += int(g or 0)
    return dist


def _role_ratio(dist_for_champ: Dict[str, int], role: str) -> float:
    if not dist_for_champ:
        return 0.0
    total = 0
    for g in dist_for_champ.values():
        try:
            total += int(g or 0)
        except Exception:
            pass
    if total <= 0:
        return 0.0
    return float(int(dist_for_champ.get(role, 0) or 0)) / float(total)


def _champ_total_games(dist_for_champ: Dict[str, int]) -> int:
    if not dist_for_champ:
        return 0
    total = 0
    for g in dist_for_champ.values():
        try:
            total += int(g or 0)
        except Exception:
            pass
    return int(total)


def _best_role_for_champ(cid: int, dist: Dict[int, Dict[str, int]], roles: List[str]) -> str:
    """
    fallback용: rr만 사용 + 동점일 때 total_games 큰 쪽 우선
    """
    m = dist.get(int(cid)) or {}
    total = _champ_total_games(m)
    if total <= 0:
        return "UNKNOWN"

    best_role = "UNKNOWN"
    best_key = None

    for r in roles:
        rr = _role_ratio(m, r)
        # rr 동점이면 total(=고정)이라 역할 간 tie-break엔 못 쓰지만,
        # deterministic 위해 role order, champ_id로 마무리.
        key = (rr, total, -roles.index(r), -int(cid))
        if best_key is None or key > best_key:
            best_key = key
            best_role = r

    return best_role


def build_enemy_role_guess_detail(enemy_ids: List[int], dist: Dict[int, Dict[str, int]]) -> Dict[int, Dict[str, Any]]:
    ids = [int(x) for x in (enemy_ids or []) if int(x) != 0]
    ids = [x for i, x in enumerate(ids) if x not in ids[:i]]

    out: Dict[int, Dict[str, Any]] = {}
    for cid in ids:
        m = dist.get(int(cid)) or {}
        total = _champ_total_games(m)
        if total <= 0:
            out[int(cid)] = {
                "total_games": 0,
                "top_role": "UNKNOWN",
                "top_games": 0,
                "top_share": 0.0,
                "role_games": {r: 0 for r in ROLES},
            }
            continue

        top_role = _best_role_for_champ(cid, dist, ROLES)
        top_games = int(m.get(top_role, 0) or 0) if top_role in ROLES else 0
        top_share = (float(top_games) / float(total)) if total > 0 else 0.0

        out[int(cid)] = {
            "total_games": int(total),
            "top_role": top_role,
            "top_games": int(top_games),
            "top_share": float(top_share),
            "role_games": {r: int(m.get(r, 0) or 0) for r in ROLES},
        }

    return out


def guess_enemy_roles_global_unique_rr(enemy_ids: List[int], dist: Dict[int, Dict[str, int]]) -> Dict[int, str]:
    """
    ✅ 전역 매칭(global matching)
    - 점수: rr만 사용 (sum rr 최대)
    - k < 5(적 챔프 2~3개 등)도 "있는 챔프만" 유니크 역할로 배정 (나머지 역할은 비움)
    - total_games=0이면 UNKNOWN 처리 + 매칭에서 제외(역할 소비 X)
    - 동점 tie-break: (rr, total_games)쌍들을 내림차순 정렬한 "패턴"으로 안정적으로 결정
      (즉 rr가 같은 선택들 사이에서 total이 큰 챔프가 더 앞에 오도록)
    """
    ids = [int(x) for x in (enemy_ids or []) if int(x) != 0]
    # 입력 순서 보존 unique
    seen = set()
    uniq_ids: List[int] = []
    for x in ids:
        if x not in seen:
            seen.add(x)
            uniq_ids.append(x)

    if not uniq_ids:
        return {}

    # 데이터 있는 챔프(=total>0)만 매칭 대상으로
    totals: Dict[int, int] = {}
    usable: List[int] = []
    unknowns: List[int] = []
    for cid in uniq_ids:
        m = dist.get(int(cid)) or {}
        t = _champ_total_games(m)
        totals[int(cid)] = int(t)
        if t > 0:
            usable.append(int(cid))
        else:
            unknowns.append(int(cid))

    # 5명 초과는 유니크 배정 불가. 현실적으로 enemy는 5 이하라 가정하지만,
    # 방어적으로: 앞 5명만 유니크 배정, 나머지는 UNKNOWN으로 둠.
    extra_unknown: List[int] = []
    if len(usable) > len(ROLES):
        extra_unknown = usable[len(ROLES):]
        usable = usable[: len(ROLES)]

    k = len(usable)
    assigned: Dict[int, str] = {}

    # UNKNOWN 먼저 확정(역할 소비 X)
    for cid in unknowns:
        assigned[int(cid)] = "UNKNOWN"
    for cid in extra_unknown:
        assigned[int(cid)] = "UNKNOWN"

    if k <= 0:
        # 전부 UNKNOWN이면 끝
        return {cid: assigned.get(cid, "UNKNOWN") for cid in uniq_ids}

    # 전역 매칭: champ 순서를 고정하고, roles의 길이 k인 순열(P(5,k))만 전부 탐색
    champs = usable[:]  # 입력 순서 유지
    best_roles_tuple = None
    best_key = None

    for roles_tuple in permutations(ROLES, k):
        # 점수: sum(rr)
        rr_list: List[Tuple[float, int, int, int]] = []
        s = 0.0
        for i, role in enumerate(roles_tuple):
            cid = champs[i]
            m = dist.get(int(cid)) or {}
            rr = _role_ratio(m, role)
            s += float(rr)
            # (rr, total, role_order, champ_id)로 패턴 구성
            rr_list.append((float(rr), int(totals.get(cid, 0)), -ROLES.index(role), -int(cid)))

        # 동점 tie-break를 위해 rr 패턴을 정렬(큰 rr 우선, rr 동점이면 total 큰 것 우선)
        rr_list_sorted = tuple(sorted(rr_list, key=lambda x: (x[0], x[1], x[2], x[3]), reverse=True))

        # 최종 key: (sum_rr, rr_pattern_sorted)
        key = (float(s), rr_list_sorted)

        if best_key is None or key > best_key:
            best_key = key
            best_roles_tuple = roles_tuple

    # best 매칭 반영
    if best_roles_tuple is None:
        # 안전망: 각 챔프 best role (중복 가능)로라도 배정
        for cid in champs:
            assigned[int(cid)] = _best_role_for_champ(cid, dist, ROLES)
    else:
        for i, role in enumerate(best_roles_tuple):
            cid = champs[i]
            assigned[int(cid)] = str(role)

    # 최종: 입력에 있던 모든 챔프에 대해 결과 반환
    out: Dict[int, str] = {}
    for cid in uniq_ids:
        out[int(cid)] = assigned.get(int(cid), "UNKNOWN")
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
    min_pick_rate: float = 0.005,
    use_champ_pool: bool = True,
    max_candidates: int = 400,
    top_n: int = 10,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    con = sqlite3.connect(db_path, check_same_thread=False)
    try:
        if not _table_exists(con, "agg_champ_role"):
            return [], {"reason": "missing table agg_champ_role"}

        my_role_db = _normalize_role_with_db(con, my_role)
        banset = set(int(x) for x in (bans or []) if int(x) != 0)

        patch_sql, patch_args = _patch_condition(patch)
        tier_sql, tier_args = _tier_condition(tier)

        q_total = f"""
          SELECT SUM(games)
          FROM agg_champ_role
          WHERE role=?
            AND {patch_sql}
            AND {tier_sql}
        """
        total_row = con.execute(q_total, (my_role_db, *patch_args, *tier_args)).fetchone()
        total_games_for_role = int((total_row[0] if total_row else 0) or 0)

        min_games_eff = int(min_games or 0)
        if min_games_eff < 1:
            min_games_eff = 1

        enemy_role_guess: Dict[int, str] = {}
        enemy_role_guess_detail: Dict[int, Dict[str, Any]] = {}
        enemy_role_guess_method = "global_unique_rr_v1"

        if enemy_picks:
            dist_for_guess = champ_role_distribution(con, patch, tier)
            enemy_role_guess = guess_enemy_roles_global_unique_rr([int(x) for x in (enemy_picks or [])], dist_for_guess)
            enemy_role_guess_detail = build_enemy_role_guess_detail(enemy_picks, dist_for_guess)

        candidates: List[int] = []

        if use_champ_pool:
            pool = [int(x) for x in (champ_pool or []) if int(x) != 0]
            pool = [x for x in pool if x not in banset]
            if not pool:
                return [], {
                    "reason": "champ_pool empty(after bans) while use_champ_pool=true",
                    "enemy_role_guess": enemy_role_guess,
                    "enemy_role_guess_method": enemy_role_guess_method,
                    "enemy_role_guess_detail": enemy_role_guess_detail,
                }
            candidates = pool
        else:
            if total_games_for_role <= 0:
                return [], {
                    "reason": "total_games_for_role is 0 (no data for role/patch/tier)",
                    "enemy_role_guess": enemy_role_guess,
                    "enemy_role_guess_method": enemy_role_guess_method,
                    "enemy_role_guess_detail": enemy_role_guess_detail,
                }

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
                pr = (g / total_games_for_role) if total_games_for_role > 0 else 0.0
                if pr >= float(min_pick_rate):
                    candidates.append(cid)

            if not candidates:
                return [], {
                    "reason": "no candidates after pick_rate filter",
                    "enemy_role_guess": enemy_role_guess,
                    "enemy_role_guess_method": enemy_role_guess_method,
                    "enemy_role_guess_detail": enemy_role_guess_detail,
                }

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

        used_fallback_roleless = False
        if not rows:
            used_fallback_roleless = True
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
            return [], {
                "reason": "no base rows",
                "enemy_role_guess": enemy_role_guess,
                "enemy_role_guess_method": enemy_role_guess_method,
                "enemy_role_guess_detail": enemy_role_guess_detail,
            }

        base_map: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            cid = int(row[0])
            g = int((row[1] if len(row) > 1 else 0) or 0)
            w = int((row[2] if len(row) > 2 else 0) or 0)
            if g <= 0:
                continue
            if g < min_games_eff:
                continue

            wr = 100.0 * (w / g)
            lb = 100.0 * _wilson_lower_bound(w, g)

            pr = None
            if total_games_for_role > 0:
                pr = g / total_games_for_role

            base_map[cid] = {"games": g, "wins": w, "base_wr": wr, "base_lb": lb, "pick_rate": pr}

        if not base_map:
            return [], {
                "reason": f"base_map empty (maybe min_games too high: min_games={min_games_eff})",
                "enemy_role_guess": enemy_role_guess,
                "enemy_role_guess_method": enemy_role_guess_method,
                "enemy_role_guess_detail": enemy_role_guess_detail,
            }

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
                            delta = _clamp(delta, -20.0, 20.0)

                            synergy_delta[my_cid] += delta
                            synergy_samples[my_cid] += g

        counter_delta: Dict[int, float] = defaultdict(float)
        counter_samples: Dict[int, int] = defaultdict(int)

        used_enemy_role_column = False
        used_role_filtered_cnt = 0
        used_roleless_cnt = 0

        if _table_exists(con, "agg_matchup_role"):
            mc = _cols(con, "agg_matchup_role")
            my_role_col = "my_role" if "my_role" in mc else ("role" if "role" in mc else None)
            enemy_role_col = "enemy_role" if "enemy_role" in mc else None
            my_c_col = "my_champ_id" if "my_champ_id" in mc else ("champ_id" if "champ_id" in mc else None)
            e_c_col = "enemy_champ_id" if "enemy_champ_id" in mc else ("other_champ_id" if "other_champ_id" in mc else None)

            used_enemy_role_column = bool(enemy_role_col)

            if my_role_col and my_c_col and e_c_col:
                for e_cid in (enemy_picks or []):
                    e_cid = int(e_cid)
                    e_role = enemy_role_guess.get(e_cid, "UNKNOWN")

                    if enemy_role_col and e_role != "UNKNOWN":
                        used_role_filtered_cnt += 1
                        q_ct = f"""
                          SELECT {my_c_col} AS my_cid, SUM(games) AS games, SUM(wins) AS wins
                          FROM agg_matchup_role
                          WHERE {my_role_col}=? AND {enemy_role_col}=? AND {e_c_col}=?
                            AND {patch_sql} AND {tier_sql}
                          GROUP BY {my_c_col}
                        """
                        args_ct: Tuple[Any, ...] = (my_role_db, e_role, e_cid, *patch_args, *tier_args)
                    else:
                        used_roleless_cnt += 1
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

        recs: List[Dict[str, Any]] = []
        for cid, b in base_map.items():
            syn = float(synergy_delta.get(cid, 0.0))
            ctd = float(counter_delta.get(cid, 0.0))

            syn = _clamp(syn, -30.0, 30.0)
            ctd = _clamp(ctd, -30.0, 30.0)

            final = float(b["base_lb"] + syn + ctd)

            pr = b.get("pick_rate", None)
            pr_pct = None
            if pr is not None:
                try:
                    pr_pct = 100.0 * float(pr)
                except Exception:
                    pr_pct = None

            recs.append(
                {
                    "champ_id": int(cid),
                    "final_score": round(final, 2),
                    "base_wr": round(float(b["base_wr"]), 2),
                    "base_lb": round(float(b["base_lb"]), 2),
                    "games": int(b["games"]),
                    "pick_rate": (None if pr is None else round(float(pr), 6)),
                    "pick_rate_pct": (None if pr_pct is None else round(float(pr_pct), 3)),
                    "counter_delta": round(ctd, 2),
                    "counter_samples": int(counter_samples.get(cid, 0)),
                    "synergy_delta": round(syn, 2),
                    "synergy_samples": int(synergy_samples.get(cid, 0)),
                }
            )

        recs.sort(key=lambda x: (x["final_score"], x["games"]), reverse=True)

        meta = {
            "reason": "ok",
            "role_used": my_role_db,
            "patch": patch,
            "tier": tier,
            "use_champ_pool": bool(use_champ_pool),
            "min_games": int(min_games_eff),
            "min_pick_rate": float(min_pick_rate),
            "total_games_for_role": int(total_games_for_role),
            "candidates_requested": int(len(candidates)),
            "base_rows_after_min_games": int(len(base_map)),
            "used_fallback_roleless": bool(used_fallback_roleless),
            "enemy_role_guess": enemy_role_guess,
            "enemy_role_guess_method": enemy_role_guess_method,
            "enemy_role_guess_detail": enemy_role_guess_detail,
            "used_enemy_role_column": bool(used_enemy_role_column),
            "counter_used_role_filtered_cnt": int(used_role_filtered_cnt),
            "counter_used_roleless_cnt": int(used_roleless_cnt),
        }

        return recs[: int(top_n)], meta
    finally:
        try:
            con.close()
        except Exception:
            pass
