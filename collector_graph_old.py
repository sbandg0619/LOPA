from __future__ import annotations

import argparse
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
load_dotenv()

from riot_api import RiotClient
from storage import connect, upsert_player, insert_match, insert_participant, upsert_agg

# ✅ 체크포인트
from checkpoint_store import load_state, save_state, clear_state


def latest_patch_major_minor() -> str:
    v = requests.get("https://ddragon.leagueoflegends.com/api/versions.json", timeout=10).json()[0]
    parts = v.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else v


def to_patch_major_minor(game_version: str) -> str:
    parts = (game_version or "").split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else (game_version or "")


def solo_rank_from_entries(entries: list[dict]) -> tuple[str | None, str | None, int | None]:
    for e in entries or []:
        if e.get("queueType") == "RANKED_SOLO_5x5":
            return e.get("tier"), e.get("rank"), int(e.get("leaguePoints", 0))
    return None, None, None


def parse_riot_id(s: str) -> tuple[str, str]:
    if "#" not in s:
        raise ValueError('seed must be like "GameName#TAG"')
    g, t = s.split("#", 1)
    return g, t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", required=True, help='Riot ID like "파뽀마블#KRI"')
    ap.add_argument("--db", default="lol_graph.db")

    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--matches_per_player", type=int, default=8)
    ap.add_argument("--max_players", type=int, default=2000)

    ap.add_argument("--target_tier", default="ALL")  # EMERALD / ALL
    ap.add_argument("--rank_refresh_hours", type=int, default=24)

    ap.add_argument("--target_patch", default="latest")   # latest or "15.24"
    ap.add_argument("--explore_non_target", type=int, default=1)
    ap.add_argument("--explore_limit", type=int, default=2)

    ap.add_argument("--tier_override", default="", help="예: EMERALD (테스트용 티어 강제)")

    # ✅ 새 옵션: 체크포인트 초기화(처음부터 다시)
    ap.add_argument("--reset_state", action="store_true", help="큐/visited 체크포인트를 초기화하고 새로 시작")

    args = ap.parse_args()

    rc = RiotClient()
    con = connect(args.db)

    target_patch = latest_patch_major_minor() if args.target_patch == "latest" else args.target_patch
    print(f"TARGET_PATCH={target_patch}")
    if args.tier_override:
        print(f"TIER_OVERRIDE={args.tier_override}")

    game_name, tag_line = parse_riot_id(args.seed)
    acc = rc.account_by_riot_id(game_name, tag_line)
    if not acc:
        print("ERROR: seed Riot ID not found (404).")
        return
    seed_puuid = acc["puuid"]

    start_time = int((datetime.now(timezone.utc) - timedelta(days=args.days)).timestamp()) if args.days and args.days > 0 else None

    now_ts = int(time.time())
    refresh_before = now_ts - args.rank_refresh_hours * 3600

    # ----------------- ✅ 체크포인트 로드/초기화 -----------------
    if args.reset_state:
        clear_state(con)
        q = deque([seed_puuid])
        seen: set[str] = set()
        total_players = 0
        saved_matches = 0
        explored_non_target = 0
        print("STATE_RESET=1 (starting fresh)")
    else:
        queue_list, visited_set, meta = load_state(con)
        q = deque(queue_list) if queue_list else deque([seed_puuid])
        seen = set(visited_set) if visited_set else set()

        total_players = int(meta.get("total_players", 0))
        saved_matches = int(meta.get("saved_matches", 0))
        explored_non_target = int(meta.get("explored_non_target", 0))

        # 같은 시드를 다시 줘도 기존 큐가 비어있지 않으면 이어서.
        if not q and seed_puuid not in seen:
            q.append(seed_puuid)

        print(f"RESUME=1 queue={len(q)} seen={len(seen)} meta_players={total_players} meta_saved_matches={saved_matches}")

    def checkpoint_save():
        meta = {
            "total_players": total_players,
            "saved_matches": saved_matches,
            "explored_non_target": explored_non_target,
            "target_patch": target_patch,
            "updated_at": int(time.time()),
        }
        save_state(con, list(q), seen, meta)

    def need_refresh_rank(puuid: str) -> bool:
        row = con.execute("SELECT last_rank_update FROM players WHERE puuid=?", (puuid,)).fetchone()
        if not row:
            return True
        return (row[0] or 0) < refresh_before

    def get_tier_cached(puuid: str) -> str | None:
        row = con.execute("SELECT tier FROM players WHERE puuid=?", (puuid,)).fetchone()
        return row[0] if row else None

    # ----------------- 메인 루프 -----------------
    try:
        while q and total_players < args.max_players:
            puuid = q.popleft()
            if puuid in seen:
                continue
            seen.add(puuid)
            total_players += 1

            match_ids = rc.match_ids(puuid, count=args.matches_per_player, start_time=start_time)

            # ---- rank 갱신(가능하면) ----
            summoner_id = None
            tier = div = lp = None

            summ = rc.summoner_by_puuid(puuid)
            if isinstance(summ, dict):
                summoner_id = summ.get("id")
                if not summoner_id and summ.get("name"):
                    summ2 = rc.summoner_by_name(summ["name"])
                    if isinstance(summ2, dict):
                        summoner_id = summ2.get("id")

            if summoner_id and need_refresh_rank(puuid):
                entries = rc.league_entries_by_summoner(summoner_id) or []
                tier, div, lp = solo_rank_from_entries(entries)

            upsert_player(con, puuid, summoner_id, tier, div, lp, int(time.time()))
            con.commit()

            # 수집 깊이 제한용
            if args.target_tier != "ALL":
                cur_tier = get_tier_cached(puuid)
                if cur_tier != args.target_tier:
                    match_ids = match_ids[:3]

            if not match_ids:
                # 체크포인트는 주기적으로 저장
                if total_players % 50 == 0:
                    checkpoint_save()
                    print(f"progress: players={total_players}, saved_matches={saved_matches}, explored_non_target={explored_non_target}, queue={len(q)} (checkpoint)")
                continue

            non_target_used = 0

            for mid in match_ids:
                m = rc.match(mid)
                if not m:
                    continue
                info = m.get("info", {})
                if info.get("queueId") != 420:
                    continue

                patch = to_patch_major_minor(info.get("gameVersion", ""))
                parts = info.get("participants", [])

                if patch == target_patch:
                    insert_match(con, mid, int(info.get("gameCreation", 0)), patch, int(info.get("queueId", 0)))

                    for p in parts:
                        p_puuid = p.get("puuid")
                        if not p_puuid:
                            continue

                        champ_id = int(p.get("championId", 0))
                        role = str(p.get("teamPosition") or "UNKNOWN")
                        win = 1 if p.get("win") else 0
                        team_id = int(p.get("teamId", 0))

                        is_new = insert_participant(con, mid, p_puuid, champ_id, role, win, team_id)

                        if is_new:
                            t = get_tier_cached(p_puuid)
                            if not t and args.tier_override:
                                t = args.tier_override
                            upsert_agg(con, patch, t, role, champ_id, win)

                        if p_puuid not in seen:
                            q.append(p_puuid)

                    con.commit()
                    saved_matches += 1

                elif args.explore_non_target == 1 and non_target_used < args.explore_limit:
                    for p in parts:
                        p_puuid = p.get("puuid")
                        if p_puuid and p_puuid not in seen:
                            q.append(p_puuid)
                    non_target_used += 1
                    explored_non_target += 1

            if total_players % 50 == 0:
                # ✅ 50명마다 진행 출력 + 체크포인트 저장
                checkpoint_save()
                print(
                    f"progress: players={total_players}, saved_matches={saved_matches}, "
                    f"explored_non_target={explored_non_target}, queue={len(q)} (checkpoint)"
                )

        # 루프 정상 종료 시에도 저장
        checkpoint_save()

    except KeyboardInterrupt:
        checkpoint_save()
        print("\nINTERRUPTED: checkpoint saved. You can resume by running the same command again.")
        return
    except Exception as e:
        # 예상치 못한 에러도 체크포인트 저장하고 종료
        checkpoint_save()
        print(f"\nERROR: {type(e).__name__}: {e}")
        print("checkpoint saved. Fix the issue and rerun to resume.")
        raise

    print("DONE")
    print(f"players_visited={total_players}, saved_matches={saved_matches}, explored_non_target={explored_non_target}, db={args.db}")


if __name__ == "__main__":
    main()
