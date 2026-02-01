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


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


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
# enemy role guess (iterative / conflict-resolve)
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
    for row in con.execute(q, (*patch_args, *tier_args)).fetchall():
        cid = row[0]
        role = row[1]
        g = row[2] if len(row) > 2 else 0
        if cid is None or role is None:
            continue
        dist[int(cid)][str(role).upper()] += int(g or 0)
    return dist


def _role_ratio(dist_for_champ: Dict[str, int], role: str) -> float:
    """games(role) / total_games (0..1). total 0이면 0."""
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
    남는 챔프 처리:
    해당 챔프의 가장 높은 비율 role을 선택.
    데이터가 없으면 UNKNOWN.
    """
    m = dist.get(int(cid)) or {}
    total = _champ_total_games(m)
    if total <= 0:
        return "UNKNOWN"

    best_role = "UNKNOWN"
    best_key = None

    for r in roles:
        rr = _role_ratio(m, r)
        g_r = int(m.get(r, 0) or 0)
        # tie-break: ratio -> role games -> total games -> role order -> champ id
        key = (rr, g_r, total, -roles.index(r), -int(cid))
        if best_key is None or key > best_key:
            best_key = key
            best_role = r

    return best_role


def guess_enemy_roles_iterative(enemy_ids: List[int], dist: Dict[int, Dict[str, int]]) -> Dict[int, str]:
    """
    ✅ 사용자 로직 반영(중요):

    - role별로 1등 챔프 임시 저장
    - 중복(한 챔프가 여러 role 1등)이면, 그 챔프는 "자기가 1등한 role 중 비율이 가장 큰 role"을 차지
    - 배정된 champ/role 제거 후 남은 대상으로 반복
    - ✅ 챔프 수 < 라인 수여도 이 반복 로직을 그대로 수행하고,
      "챔피언마다 라인이 하나씩 정해진 순간" 종료한다. (남는 라인은 그냥 남김)
    - 데이터 없으면 UNKNOWN
    """
    ids = [int(x) for x in (enemy_ids or []) if int(x) != 0]
    ids = [x for i, x in enumerate(ids) if x not in ids[:i]]  # unique
    if not ids:
        return {}

    remaining_champs = ids[:]
    remaining_roles = ROLES[:]  # 남는 라인이 생겨도 OK
    assigned: Dict[int, str] = {}

    guard = 0
    while remaining_champs and remaining_roles and guard < 50:
        guard += 1

        # 1) role별 winner champ 찾기
        role_winner: Dict[str, int] = {}
        for role in remaining_roles:
            best_cid = None
            best_key = None

            for cid in remaining_champs:
                m = dist.get(int(cid)) or {}
                total = _champ_total_games(m)
                rr = _role_ratio(m, role) if total > 0 else 0.0
                g_r = int(m.get(role, 0) or 0)

                # tie-break:
                # ratio -> role games -> total games -> champ id 작은 쪽 선호
                key = (rr, g_r, total, -int(cid))
                if best_key is None or key > best_key:
                    best_key = key
                    best_cid = cid

            if best_cid is not None:
                role_winner[role] = int(best_cid)

        # 2) champ별로 자기가 winner인 role들 모으기
        champ_wins: Dict[int, List[str]] = defaultdict(list)
        for role, cid in role_winner.items():
            champ_wins[int(cid)].append(role)

        # 3) 충돌 해결: 여러 role winner면, 그중 비율이 최대인 role 하나만 선택
        newly_assigned: List[Tuple[int, str]] = []
        for cid, roles_won in champ_wins.items():
            if cid in assigned:
                continue
            if cid not in remaining_champs:
                continue

            m = dist.get(int(cid)) or {}
            total = _champ_total_games(m)

            if total <= 0:
                chosen_role = "UNKNOWN"
            else:
                chosen_role = None
                chosen_key = None
                for r in roles_won:
                    rr = _role_ratio(m, r)
                    g_r = int(m.get(r, 0) or 0)
                    # ratio -> role games -> total games -> role order -> champ id
                    key = (rr, g_r, total, -remaining_roles.index(r), -cid)
                    if chosen_key is None or key > chosen_key:
                        chosen_key = key
                        chosen_role = r
                chosen_role = chosen_role or "UNKNOWN"

            newly_assigned.append((cid, chosen_role))

        if not newly_assigned:
            # 막히면 강제 배정: 남은 역할 중 best를 하나 찝어 배정하고 진행
            cid = min(remaining_champs)
            role = _best_role_for_champ(cid, dist, remaining_roles)
            assigned[cid] = role
            if cid in remaining_champs:
                remaining_champs.remove(cid)
            if role in remaining_roles:
                remaining_roles.remove(role)
            continue

        # 4) 확정 + 제거
        for cid, role in newly_assigned:
            assigned[int(cid)] = role

        assigned_champs_set = set(cid for cid, _ in newly_assigned)
        remaining_champs = [c for c in remaining_champs if c not in assigned_champs_set]

        assigned_roles_set = set(r for _, r in newly_assigned if r in remaining_roles)
        remaining_roles = [r for r in remaining_roles if r not in assigned_roles_set]

    # remaining_roles가 먼저 바닥나서 챔프가 남으면: 각자 best role(중복 허용)
    if remaining_champs:
        for cid in remaining_champs:
            if cid in assigned:
                continue
            assigned[cid] = _best_role_for_champ(cid, dist, ROLES)

    out2: Dict[int, str] = {}
    for cid in ids:
        out2[cid] = assigned.get(cid, _best_role_for_champ(cid, dist, ROLES))
    return out2


def build_enemy_role_guess_detail(enemy_role_guess: Dict[int, str], dist: Dict[int, Dict[str, int]]) -> Dict[str, Dict[str, Any]]:
    """
    UI 표시용:
      meta.enemy_role_guess_detail[cid] = {
        top_share, top_games, total_games
      }
    여기서 top_*는 "추정된 role"에 대한 샘플/비율로 사용.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for cid, role in (enemy_role_guess or {}).items():
        m = dist.get(int(cid)) or {}
        total = _champ_total_games(m)
        g = int(m.get(role, 0) or 0) if role and role != "UNKNOWN" else 0
        share = (float(g) / float(total)) if total > 0 else 0.0
        out[str(int(cid))] = {
            "top_share": share,
            "top_games": g,
            "total_games": total,
        }
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
    min_games: int = 30,              # ✅ 실제 필터로 사용(>=1 권장)
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
        banset = set(int(x) for x in (bans or []) if int(x) != 0)

        patch_sql, patch_args = _patch_condition(patch)
        tier_sql, tier_args = _tier_condition(tier)

        # ✅ (핵심) total_games_for_role 계산: pick_rate 계산/표시용
        q_total = f"""
          SELECT SUM(games)
          FROM agg_champ_role
          WHERE role=?
            AND {patch_sql}
            AND {tier_sql}
        """
        total_row = con.execute(q_total, (my_role_db, *patch_args, *tier_args)).fetchone()
        total_games_for_role = int((total_row[0] if total_row else 0) or 0)

        # min_games 안전 보정
        min_games_eff = int(min_games or 0)
        if min_games_eff < 1:
            min_games_eff = 1

        # ✅ enemy role guess는 "표시/카운터용"으로 항상 meta에 실어줌
        enemy_role_guess: Dict[int, str] = {}
        enemy_role_guess_detail: Dict[str, Dict[str, Any]] = {}
        dist_for_guess: Dict[int, Dict[str, int]] = {}
        if enemy_picks:
            dist_for_guess = champ_role_distribution(con, patch, tier)
            enemy_role_guess = guess_enemy_roles_iterative([int(x) for x in (enemy_picks or [])], dist_for_guess)
            enemy_role_guess_detail = build_enemy_role_guess_detail(enemy_role_guess, dist_for_guess)

        # -------------------------
        # 1) candidate set 만들기
        # -------------------------
        candidates: List[int] = []

        if use_champ_pool:
            pool = [int(x) for x in (champ_pool or []) if int(x) != 0]
            pool = [x for x in pool if x not in banset]
            if not pool:
                return [], {
                    "reason": "champ_pool empty(after bans) while use_champ_pool=true",
                    "enemy_role_guess": enemy_role_guess,
                    "enemy_role_guess_detail": enemy_role_guess_detail,
                    "enemy_role_guess_method": "iterative_v1",
                }
            candidates = pool
        else:
            if total_games_for_role <= 0:
                return [], {
                    "reason": "total_games_for_role is 0 (no data for role/patch/tier)",
                    "enemy_role_guess": enemy_role_guess,
                    "enemy_role_guess_detail": enemy_role_guess_detail,
                    "enemy_role_guess_method": "iterative_v1",
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
                    "enemy_role_guess_detail": enemy_role_guess_detail,
                    "enemy_role_guess_method": "iterative_v1",
                }

        # -------------------------
        # 2) base
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
                "enemy_role_guess_detail": enemy_role_guess_detail,
                "enemy_role_guess_method": "iterative_v1",
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

            base_map[cid] = {
                "games": g,
                "wins": w,
                "base_wr": wr,
                "base_lb": lb,
                "pick_rate": pr,
            }

        if not base_map:
            return [], {
                "reason": f"base_map empty (maybe min_games too high: min_games={min_games_eff})",
                "enemy_role_guess": enemy_role_guess,
                "enemy_role_guess_detail": enemy_role_guess_detail,
                "enemy_role_guess_method": "iterative_v1",
            }

        # -------------------------
        # 3) synergy
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
                            delta = _clamp(delta, -20.0, 20.0)

                            synergy_delta[my_cid] += delta
                            synergy_samples[my_cid] += g

        # -------------------------
        # 4) counter + enemy_role_guess 사용
        # -------------------------
        counter_delta: Dict[int, float] = defaultdict(float)
        counter_samples: Dict[int, int] = defaultdict(int)

        used_enemy_role_column = False

        if _table_exists(con, "agg_matchup_role"):
            mc = _cols(con, "agg_matchup_role")
            my_role_col = "my_role" if "my_role" in mc else ("role" if "role" in mc else None)
            enemy_role_col = "enemy_role" if "enemy_role" in mc else None
            my_c_col = "my_champ_id" if "my_champ_id" in mc else ("champ_id" if "champ_id" in mc else None)
            e_c_col = "enemy_champ_id" if "enemy_champ_id" in mc else ("other_champ_id" if "other_champ_id" in mc else None)

            if enemy_role_col:
                used_enemy_role_column = True

            if my_role_col and my_c_col and e_c_col:
                for e_cid in (enemy_picks or []):
                    e_cid = int(e_cid)
                    e_role = enemy_role_guess.get(e_cid, "UNKNOWN")

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

            # ✅ UI 표시용 + 카운터용
            "enemy_role_guess": enemy_role_guess,
            "enemy_role_guess_detail": enemy_role_guess_detail,
            "enemy_role_guess_method": "iterative_v1",
            "used_enemy_role_column": bool(used_enemy_role_column),
        }

        return recs[: int(top_n)], meta
    finally:
        try:
            con.close()
        except Exception:
            pass
