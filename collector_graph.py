from __future__ import annotations

import argparse
import os
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from statistics import median
from pathlib import Path

import requests
from dotenv import load_dotenv

# ✅ CWD가 아니라 "이 파일이 있는 폴더"의 .env를 명시적으로 로드
_ENV_PATH = Path(__file__).resolve().with_name(".env")
if _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH, override=False)
else:
    load_dotenv(override=False)

from riot_api import RiotClient
from storage import (
    connect,
    upsert_player, insert_match, insert_participant,
    insert_rank_snapshot, upsert_match_participant_rank, upsert_match_tier,
    insert_match_bans,
    ROLES,
)
from checkpoint_store import load_state, save_state, clear_state


# ---------- patch helpers ----------
def _versions() -> list[str]:
    return requests.get("https://ddragon.leagueoflegends.com/api/versions.json", timeout=10).json()

def to_patch_major_minor(game_version: str) -> str:
    parts = (game_version or "").split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else (game_version or "")

def latest_two_patches_major_minor() -> tuple[str, str]:
    vers = _versions()
    seen = []
    for v in vers:
        mm = ".".join(v.split(".")[:2])
        if mm and (not seen or mm != seen[-1]):
            if mm not in seen:
                seen.append(mm)
        if len(seen) >= 2:
            break
    if not seen:
        return ("", "")
    if len(seen) == 1:
        return (seen[0], seen[0])
    return (seen[0], seen[1])


# ---------- tier helpers ----------
TIER_ORDER = {
    "IRON": 1, "BRONZE": 2, "SILVER": 3, "GOLD": 4, "PLATINUM": 5,
    "EMERALD": 6, "DIAMOND": 7, "MASTER": 8, "GRANDMASTER": 9, "CHALLENGER": 10,
}
DIV_ORDER = {"IV": 0, "III": 1, "II": 2, "I": 3}

def solo_rank_from_entries(entries: list[dict]) -> tuple[str | None, str | None, int | None]:
    for e in entries or []:
        if e.get("queueType") == "RANKED_SOLO_5x5":
            return e.get("tier"), e.get("rank"), int(e.get("leaguePoints", 0))
    return None, None, None

def tier_to_score(tier: str | None, div: str | None, lp: int | None) -> float | None:
    if not tier or tier not in TIER_ORDER:
        return None
    base = float(TIER_ORDER[tier])
    if div and div in DIV_ORDER:
        base += DIV_ORDER[div] / 4.0
    return base

def score_to_tier_label(score: float | None) -> str | None:
    if score is None:
        return None
    nearest = min(TIER_ORDER.items(), key=lambda kv: abs(kv[1] - score))
    return nearest[0]


def parse_riot_id(s: str) -> tuple[str, str]:
    if "#" not in s:
        raise ValueError('seed must be like "GameName#TAG"')
    g, t = s.split("#", 1)
    return g, t


def _set_env_if_missing(key: str, value: str):
    if os.getenv(key) is None:
        os.environ[key] = str(value)

def _apply_mode_env(mode: str, throttle_1s: int | None, throttle_120s: int | None, max_tries: int | None, timeout: float | None):
    if mode not in ("manual", "dev", "prod"):
        return

    if mode == "dev":
        _set_env_if_missing("RIOT_MAX_TRIES", "6")
        _set_env_if_missing("RIOT_TIMEOUT", "15")
        _set_env_if_missing("RIOT_THROTTLE_1S", "15")
        _set_env_if_missing("RIOT_THROTTLE_120S", "80")
    elif mode == "prod":
        _set_env_if_missing("RIOT_MAX_TRIES", "8")
        _set_env_if_missing("RIOT_TIMEOUT", "15")
        _set_env_if_missing("RIOT_THROTTLE_1S", "19")
        _set_env_if_missing("RIOT_THROTTLE_120S", "95")

    if max_tries is not None:
        os.environ["RIOT_MAX_TRIES"] = str(int(max_tries))
    if timeout is not None:
        os.environ["RIOT_TIMEOUT"] = str(float(timeout))
    if throttle_1s is not None:
        os.environ["RIOT_THROTTLE_1S"] = str(int(throttle_1s))
    if throttle_120s is not None:
        os.environ["RIOT_THROTTLE_120S"] = str(int(throttle_120s))


def main():
    ap = argparse.ArgumentParser()

    ap.add_argument("--seed", required=True, help='Riot ID like "파뽀마블#KRI"')
    ap.add_argument("--db", default="lol_graph.db")
    ap.add_argument("--reset_db", action="store_true", help="DB 파일을 삭제하고 새로 시작(주의)")

    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--matches_per_player", type=int, default=20)
    ap.add_argument("--max_players", type=int, default=2000)

    ap.add_argument("--target_patch", default="latest2")
    ap.add_argument("--latest_only", action="store_true", help="최신 패치만 강제 (target_patch=latest로 덮어씀)")

    ap.add_argument("--explore_non_target", type=int, default=1)
    ap.add_argument("--explore_limit", type=int, default=2)

    ap.add_argument("--reset_state", action="store_true", help="큐/visited 체크포인트 초기화")

    ap.add_argument("--fast", action="store_true", help="(deprecated) kept for compatibility. Rank is still collected.")
    ap.add_argument("--collect_rank", action="store_true", help="(deprecated) kept for compatibility. Rank is forced ON.")

    ap.add_argument("--rank_refresh_hours", type=int, default=24)
    ap.add_argument("--tier_override", default="", help="테스트용: 참가자 tier 비어있으면 강제로 넣음")
    ap.add_argument("--match_tier_method", default="median", choices=["median", "mean", "mode", "trimmed_mean"])
    ap.add_argument("--match_tier_min_known", type=int, default=6)

    ap.add_argument("--commit_every", type=int, default=50)

    # ✅ 새 옵션: 진행 로그/체크포인트 주기
    ap.add_argument(
        "--progress_every_players",
        type=int,
        default=1,
        help="진행 로그 출력 주기(visited player 기준). 1이면 매 플레이어마다 출력",
    )
    ap.add_argument(
        "--checkpoint_every_players",
        type=int,
        default=50,
        help="몇 플레이어마다 commit+checkpoint 저장할지(기존 50 유지)",
    )

    ap.add_argument("--debug", action="store_true")

    ap.add_argument("--mode", default="manual", choices=["manual", "dev", "prod"])
    ap.add_argument("--throttle_1s", type=int, default=None)
    ap.add_argument("--throttle_120s", type=int, default=None)
    ap.add_argument("--max_tries", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=None)

    args = ap.parse_args()

    if args.reset_db and os.path.exists(args.db):
        os.remove(args.db)

    if args.latest_only:
        args.target_patch = "latest"

    _apply_mode_env(
        mode=args.mode,
        throttle_1s=args.throttle_1s,
        throttle_120s=args.throttle_120s,
        max_tries=args.max_tries,
        timeout=args.timeout,
    )

    rc = RiotClient()
    con = connect(args.db)

    # ✅ 랭크 수집은 무조건 ON
    collect_rank = True

    # target patches 결정
    if args.target_patch == "latest":
        p1, _ = latest_two_patches_major_minor()
        target_patches = {p1}
    elif args.target_patch == "latest2":
        p1, p2 = latest_two_patches_major_minor()
        target_patches = {p1, p2}
    else:
        target_patches = {args.target_patch}

    print(f"TARGET_PATCHES={sorted(target_patches)}")
    print(f"MODE={args.mode} (env RIOT_THROTTLE_1S={os.getenv('RIOT_THROTTLE_1S')}, RIOT_THROTTLE_120S={os.getenv('RIOT_THROTTLE_120S')}, RIOT_MAX_TRIES={os.getenv('RIOT_MAX_TRIES')}, RIOT_TIMEOUT={os.getenv('RIOT_TIMEOUT')})")
    print("RANK_COLLECT=ON (forced)")
    if args.tier_override:
        print(f"TIER_OVERRIDE={args.tier_override}")
    print(f"MATCH_TIER_METHOD={args.match_tier_method}, MIN_KNOWN={args.match_tier_min_known}")

    game_name, tag_line = parse_riot_id(args.seed)
    acc = rc.account_by_riot_id(game_name, tag_line)
    if not acc:
        print("ERROR: seed Riot ID not found (404).")
        return
    seed_puuid = acc["puuid"]

    start_time = int((datetime.now(timezone.utc) - timedelta(days=args.days)).timestamp()) if args.days and args.days > 0 else None

    now_ts = int(time.time())
    refresh_before = now_ts - args.rank_refresh_hours * 3600

    progress_every = max(1, int(args.progress_every_players))
    checkpoint_every_players = max(1, int(args.checkpoint_every_players))
    t0 = time.time()

    def _ppm() -> float:
        el = time.time() - t0
        if el <= 0:
            return 0.0
        return (total_players / el) * 60.0

    def _print_player_progress(tag: str, saved_this_player: int, already_have_skip: int, queue_skip: int, patch_skip: int, did_rank_update: bool, tier_val):
        print(
            f"{tag}: player#{total_players} "
            f"saved_matches={saved_matches} "
            f"queue={len(q)} "
            f"this_saved={saved_this_player} "
            f"have_skip={already_have_skip} queue_skip={queue_skip} patch_skip={patch_skip} "
            f"explored_non_target={explored_non_target} "
            f"rank_update={'Y' if did_rank_update else 'N'} tier={tier_val} "
            f"ppm={_ppm():.1f}"
        )

    # -------- checkpoint helpers (meta merge) --------
    COLLECTOR_META_KEYS = {
        "total_players",
        "saved_matches",
        "explored_non_target",
        "target_patches",
        "updated_at",
    }

    def _load_meta_only():
        try:
            _, _, m = load_state(con)
            return m if isinstance(m, dict) else {}
        except Exception:
            return {}

    def _save_state_merge_meta(queue_list, visited_set, collector_updates: dict):
        old_meta = _load_meta_only()
        merged = dict(old_meta) if isinstance(old_meta, dict) else {}
        merged.update(collector_updates or {})
        save_state(con, queue_list, visited_set, merged)

    def _reset_collector_state(reason: str):
        old_meta = _load_meta_only()
        kept = {}
        if isinstance(old_meta, dict):
            kept = {k: v for k, v in old_meta.items() if k not in COLLECTOR_META_KEYS}

        curr_tp = ",".join(sorted(target_patches))
        kept.update({
            "total_players": 0,
            "saved_matches": 0,
            "explored_non_target": 0,
            "target_patches": curr_tp,
            "updated_at": int(time.time()),
        })

        _save_state_merge_meta([seed_puuid], set(), kept)

        print(f"STATE_RESET=1 ({reason})")
        return deque([seed_puuid]), set(), 0, 0, 0

    # -------- checkpoint load/reset --------
    if args.reset_state:
        q, seen, total_players, saved_matches, explored_non_target = _reset_collector_state("manual reset_state")
    else:
        queue_list, visited_set, meta = load_state(con)

        prev_tp = ""
        try:
            prev_tp = (meta.get("target_patches") or "").strip()
        except Exception:
            prev_tp = ""

        curr_tp = ",".join(sorted(target_patches))
        auto_reset = (args.target_patch in ("latest", "latest2"))

        if auto_reset and prev_tp and prev_tp != curr_tp:
            print(f"[CP_RESET] target_patches changed: {prev_tp} -> {curr_tp} (auto reset state)")
            q, seen, total_players, saved_matches, explored_non_target = _reset_collector_state("auto; patch changed")
        else:
            q = deque(queue_list) if queue_list else deque([seed_puuid])
            seen = set(visited_set) if visited_set else set()

            total_players = int(meta.get("total_players", 0))
            saved_matches = int(meta.get("saved_matches", 0))
            explored_non_target = int(meta.get("explored_non_target", 0))

            if not q and seed_puuid not in seen:
                q.append(seed_puuid)

            print(f"RESUME=1 queue={len(q)} seen={len(seen)} meta_players={total_players} meta_saved_matches={saved_matches}")

    def checkpoint_save():
        collector_meta = {
            "total_players": total_players,
            "saved_matches": saved_matches,
            "explored_non_target": explored_non_target,
            "target_patches": ",".join(sorted(target_patches)),
            "updated_at": int(time.time()),
        }
        _save_state_merge_meta(list(q), seen, collector_meta)

    # ----------------------------
    # rank cache helpers (FIX)
    # ----------------------------
    def get_player_row_cached(puuid: str):
        return con.execute(
            "SELECT summoner_id, tier, division, league_points, last_rank_update FROM players WHERE puuid=?",
            (puuid,),
        ).fetchone()

    def need_refresh_rank(puuid: str) -> bool:
        """
        ✅ FIX:
        - tier가 비어있으면 무조건 다시 시도
        - last_rank_update가 오래됐으면 다시 시도
        """
        row = get_player_row_cached(puuid)
        if not row:
            return True
        _summoner_id, t, d, lp, last_upd = row
        if not t:
            return True
        return (last_upd or 0) < refresh_before

    def get_player_rank_cached(puuid: str) -> tuple[str | None, str | None, int | None]:
        row = con.execute("SELECT tier, division, league_points FROM players WHERE puuid=?", (puuid,)).fetchone()
        if not row:
            return None, None, None
        return row[0], row[1], row[2]

    def compute_match_tier(scores: list[float]) -> float:
        method = args.match_tier_method
        s = sorted(scores)
        if method == "median":
            return float(median(s))
        if method == "mean":
            return float(sum(s) / len(s))
        if method == "trimmed_mean":
            if len(s) <= 2:
                return float(sum(s) / len(s))
            s2 = s[1:-1]
            return float(sum(s2) / len(s2))
        buckets = {}
        for x in s:
            b = round(x)
            buckets[b] = buckets.get(b, 0) + 1
        best = max(buckets.items(), key=lambda kv: kv[1])[0]
        return float(best)

    def _existing_match_ids(mids: list[str]) -> set[str]:
        if not mids:
            return set()
        qmarks = ",".join(["?"] * len(mids))
        rows = con.execute(f"SELECT match_id FROM matches WHERE match_id IN ({qmarks})", tuple(mids)).fetchall()
        return {r[0] for r in rows} if rows else set()

    commit_every = max(1, int(args.commit_every))
    since_commit = 0

    try:
        while q and total_players < args.max_players:
            puuid = q.popleft()
            if puuid in seen:
                continue
            seen.add(puuid)
            total_players += 1

            # 기본 카운터(진행 로그용)
            saved_this_player = 0
            queue_skip = 0
            patch_skip = 0
            already_have_skip = 0
            did_rank_update = False
            tier = None

            match_ids = rc.match_ids(puuid, count=args.matches_per_player, start_time=start_time)
            if not match_ids:
                # ✅ 매 플레이어 로그
                if total_players % progress_every == 0:
                    _print_player_progress("progress", saved_this_player, already_have_skip, queue_skip, patch_skip, did_rank_update, tier)

                # ✅ 체크포인트 주기
                if total_players % checkpoint_every_players == 0:
                    con.commit()
                    checkpoint_save()
                    print(f"checkpoint: players={total_players}, saved_matches={saved_matches}, explored_non_target={explored_non_target}, queue={len(q)}")
                    if hasattr(rc, "rate_report"):
                        try:
                            print(rc.rate_report())
                        except Exception:
                            pass
                continue

            exist_mids = _existing_match_ids(match_ids)

            # ---- rank 갱신(강제 ON) ----
            summoner_id = None
            div = lp = None

            prev_row = get_player_row_cached(puuid)
            prev_summoner_id = prev_row[0] if prev_row else None
            prev_last_update = (prev_row[4] if prev_row else 0) or 0

            summ = rc.summoner_by_puuid(puuid)
            if isinstance(summ, dict):
                summoner_id = summ.get("id") or prev_summoner_id
                if not summoner_id and summ.get("name"):
                    summ2 = rc.summoner_by_name(summ["name"])
                    if isinstance(summ2, dict):
                        summoner_id = summ2.get("id")

            if summoner_id and need_refresh_rank(puuid):
                try:
                    entries = rc.league_entries_by_summoner(summoner_id) or []
                    tier, div, lp = solo_rank_from_entries(entries)
                    if tier:
                        did_rank_update = True
                except Exception:
                    did_rank_update = False

            new_last_rank_update = int(time.time()) if did_rank_update else int(prev_last_update)
            upsert_player(con, puuid, summoner_id, tier, div, lp, new_last_rank_update)

            non_target_used = 0

            for mid in match_ids:
                if mid in exist_mids:
                    already_have_skip += 1
                    continue

                m = rc.match(mid)
                if not m:
                    continue
                info = m.get("info", {})
                if info.get("queueId") != 420:
                    queue_skip += 1
                    continue

                patch = to_patch_major_minor(info.get("gameVersion", ""))
                parts = info.get("participants", [])

                if patch in target_patches:
                    insert_match(con, mid, int(info.get("gameCreation", 0)), patch, int(info.get("queueId", 0)))

                    # bans 저장
                    teams = info.get("teams") or []
                    bans_rows = []
                    for t in teams:
                        team_id = int(t.get("teamId", 0))
                        bans = t.get("bans") or []
                        for idx, b in enumerate(bans[:5], start=1):
                            champ = int(b.get("championId", 0))
                            if champ <= 0:
                                champ = -1
                            bans_rows.append((team_id, idx, champ))
                    if bans_rows:
                        insert_match_bans(con, mid, bans_rows)

                    # rank snapshot (현재는 cached 기반)
                    as_of_ts = int(time.time())
                    rank_cache: dict[str, tuple[str | None, str | None, int | None]] = {}

                    part_puuids = [p.get("puuid") for p in parts if p.get("puuid")]
                    for pp in part_puuids:
                        t, d, lpp = get_player_rank_cached(pp)
                        if (not t) and args.tier_override:
                            t = args.tier_override
                        rank_cache[pp] = (t, d, lpp)
                        insert_rank_snapshot(con, pp, as_of_ts, t, d, lpp, source="collector_asof")
                        upsert_match_participant_rank(con, mid, pp, as_of_ts, t, d, lpp)

                    # participants 저장 + match_tier 계산
                    match_scores = []
                    known_cnt = 0

                    for p in parts:
                        p_puuid = p.get("puuid")
                        if not p_puuid:
                            continue

                        champ_id = int(p.get("championId", 0))
                        role = str(p.get("teamPosition") or "UNKNOWN")
                        win = 1 if p.get("win") else 0
                        team_id = int(p.get("teamId", 0))

                        insert_participant(con, mid, p_puuid, champ_id, role, win, team_id)

                        t, d, lpp = rank_cache.get(p_puuid, (None, None, None))
                        sc = tier_to_score(t, d, lpp)
                        if sc is not None:
                            match_scores.append(sc)
                            known_cnt += 1

                        if p_puuid not in seen:
                            q.append(p_puuid)

                    if known_cnt >= args.match_tier_min_known and match_scores:
                        mt_score = compute_match_tier(match_scores)
                        mt_label = score_to_tier_label(mt_score)
                        upsert_match_tier(con, mid, patch, args.match_tier_method, mt_label, mt_score, known_cnt, as_of_ts)
                    else:
                        upsert_match_tier(con, mid, patch, args.match_tier_method, None, None, known_cnt, as_of_ts)

                    saved_matches += 1
                    saved_this_player += 1
                    since_commit += 1

                    if since_commit >= commit_every:
                        con.commit()
                        since_commit = 0

                else:
                    patch_skip += 1
                    if args.explore_non_target == 1 and non_target_used < args.explore_limit:
                        for p in parts:
                            p_puuid = p.get("puuid")
                            if p_puuid and p_puuid not in seen:
                                q.append(p_puuid)
                        non_target_used += 1
                        explored_non_target += 1

            # ✅ 매 플레이어 로그(기본 ON)
            if total_players % progress_every == 0:
                _print_player_progress("progress", saved_this_player, already_have_skip, queue_skip, patch_skip, did_rank_update, tier)

            # ✅ 체크포인트 주기(기존 50 유지 가능)
            if total_players % checkpoint_every_players == 0:
                con.commit()
                checkpoint_save()
                print(f"checkpoint: players={total_players}, saved_matches={saved_matches}, explored_non_target={explored_non_target}, queue={len(q)}")
                if hasattr(rc, "rate_report"):
                    try:
                        print(rc.rate_report())
                    except Exception:
                        pass

        con.commit()
        checkpoint_save()

    except KeyboardInterrupt:
        con.commit()
        checkpoint_save()
        print("\nINTERRUPTED: checkpoint saved. You can resume by running the same command again.")
        return
    except Exception as e:
        con.commit()
        checkpoint_save()
        print(f"\nERROR: {type(e).__name__}: {e}")
        print("checkpoint saved. Fix the issue and rerun to resume.")
        raise

    print("DONE")
    print(f"players_visited={total_players}, saved_matches={saved_matches}, explored_non_target={explored_non_target}, db={args.db}")


if __name__ == "__main__":
    main()
