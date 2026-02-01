# storage.py
from __future__ import annotations

import sqlite3
from typing import Optional, Iterable, Tuple, List

# collector_graph.py 호환용(라인 상수)
ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]


# ----------------- DB connect -----------------
def connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    _init_schema(con)
    _migrate_schema(con)  # ✅ 기존 DB 자동 마이그레이션
    return con


# ----------------- schema -----------------
def _init_schema(con: sqlite3.Connection):
    # players
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS players (
          puuid TEXT PRIMARY KEY,
          summoner_id TEXT,
          tier TEXT,
          division TEXT,
          league_points INTEGER,
          last_rank_update INTEGER
        )
        """
    )

    # matches
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS matches (
          match_id TEXT PRIMARY KEY,
          game_creation INTEGER,
          patch TEXT,
          queue_id INTEGER
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_matches_patch ON matches(patch);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_matches_game_creation ON matches(game_creation);")

    # participants
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS participants (
          match_id TEXT NOT NULL,
          puuid TEXT NOT NULL,
          champ_id INTEGER,
          role TEXT,
          win INTEGER,
          team_id INTEGER,
          PRIMARY KEY (match_id, puuid)
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_participants_champ ON participants(champ_id);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_participants_role ON participants(role);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_participants_match ON participants(match_id);")

    # agg_champ_role
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS agg_champ_role (
          patch TEXT NOT NULL,
          tier TEXT,
          role TEXT NOT NULL,
          champ_id INTEGER NOT NULL,
          games INTEGER NOT NULL,
          wins INTEGER NOT NULL,
          PRIMARY KEY (patch, tier, role, champ_id)
        )
        """
    )

    # rank snapshots
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS rank_snapshots (
          puuid TEXT NOT NULL,
          as_of_ts INTEGER NOT NULL,
          tier TEXT,
          division TEXT,
          league_points INTEGER,
          source TEXT,
          PRIMARY KEY (puuid, as_of_ts)
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_rank_snapshots_puuid ON rank_snapshots(puuid);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_rank_snapshots_ts ON rank_snapshots(as_of_ts);")

    # match participant rank
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS match_participant_rank (
          match_id TEXT NOT NULL,
          puuid TEXT NOT NULL,
          as_of_ts INTEGER NOT NULL,
          tier TEXT,
          division TEXT,
          league_points INTEGER,
          PRIMARY KEY (match_id, puuid)
        )
        """
    )

    # match_tier
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS match_tier (
          match_id TEXT PRIMARY KEY,
          patch TEXT,
          method TEXT,
          tier_label TEXT,
          tier_score REAL,
          known_cnt INTEGER,
          as_of_ts INTEGER
        )
        """
    )

    # ✅ match_bans
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS match_bans (
          match_id TEXT NOT NULL,
          team_id INTEGER NOT NULL,
          ban_slot INTEGER NOT NULL,
          champ_id INTEGER NOT NULL,
          PRIMARY KEY (match_id, team_id, ban_slot)
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_match_bans_match ON match_bans(match_id);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_match_bans_champ ON match_bans(champ_id);")

    # ✅ agg_matchup_role
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS agg_matchup_role (
          patch TEXT NOT NULL,
          tier TEXT,
          my_role TEXT NOT NULL,
          enemy_role TEXT NOT NULL,
          my_champ_id INTEGER NOT NULL,
          enemy_champ_id INTEGER NOT NULL,
          games INTEGER NOT NULL,
          wins INTEGER NOT NULL,
          PRIMARY KEY (patch, tier, my_role, enemy_role, my_champ_id, enemy_champ_id)
        )
        """
    )

    # ✅ crawl_state (체크포인트 저장용)
    # - 구버전 DB는 updated_at 이 없을 수 있어서 마이그레이션에서 보강함
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS crawl_state (
          k TEXT PRIMARY KEY,
          v TEXT,
          updated_at INTEGER
        )
        """
    )

    con.commit()


# ----------------- schema migration -----------------
def _table_columns(con: sqlite3.Connection, table: str) -> List[str]:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]  # name


def _migrate_schema(con: sqlite3.Connection):
    """
    기존 DB가 구버전 스키마여도 최신 코드가 돌아가게 자동 보강.
    지금 터진 케이스: crawl_state에 updated_at 컬럼이 없음.
    """
    # crawl_state가 존재하면 updated_at 컬럼이 있는지 확인 후 없으면 추가
    try:
        cols = _table_columns(con, "crawl_state")
    except sqlite3.OperationalError:
        cols = []

    if cols and "updated_at" not in cols:
        con.execute("ALTER TABLE crawl_state ADD COLUMN updated_at INTEGER;")
        con.commit()


# ----------------- basic writes -----------------
def upsert_player(con: sqlite3.Connection, puuid: str, summoner_id: Optional[str],
                  tier: Optional[str], division: Optional[str], lp: Optional[int],
                  last_rank_update: int):
    con.execute(
        """
        INSERT INTO players(puuid, summoner_id, tier, division, league_points, last_rank_update)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(puuid) DO UPDATE SET
          summoner_id=excluded.summoner_id,
          tier=excluded.tier,
          division=excluded.division,
          league_points=excluded.league_points,
          last_rank_update=excluded.last_rank_update
        """,
        (puuid, summoner_id, tier, division, lp, last_rank_update),
    )


def insert_match(con: sqlite3.Connection, match_id: str, game_creation: int, patch: str, queue_id: int):
    con.execute(
        """
        INSERT OR IGNORE INTO matches(match_id, game_creation, patch, queue_id)
        VALUES(?,?,?,?)
        """,
        (match_id, game_creation, patch, queue_id),
    )


def insert_participant(con: sqlite3.Connection, match_id: str, puuid: str, champ_id: int, role: str, win: int, team_id: int) -> bool:
    cur = con.execute(
        """
        INSERT OR IGNORE INTO participants(match_id, puuid, champ_id, role, win, team_id)
        VALUES(?,?,?,?,?,?)
        """,
        (match_id, puuid, champ_id, role, win, team_id),
    )
    return cur.rowcount > 0


def upsert_agg(con: sqlite3.Connection, patch: str, tier: Optional[str], role: str, champ_id: int, win: int):
    con.execute(
        """
        INSERT INTO agg_champ_role(patch, tier, role, champ_id, games, wins)
        VALUES(?,?,?,?,1,?)
        ON CONFLICT(patch, tier, role, champ_id) DO UPDATE SET
          games = games + 1,
          wins  = wins + excluded.wins
        """,
        (patch, tier, role, champ_id, 1 if win else 0),
    )


def insert_rank_snapshot(con: sqlite3.Connection, puuid: str, as_of_ts: int,
                         tier: Optional[str], division: Optional[str], lp: Optional[int],
                         source: str = "collector_asof"):
    con.execute(
        """
        INSERT OR REPLACE INTO rank_snapshots(puuid, as_of_ts, tier, division, league_points, source)
        VALUES(?,?,?,?,?,?)
        """,
        (puuid, as_of_ts, tier, division, lp, source),
    )


def upsert_match_participant_rank(con: sqlite3.Connection, match_id: str, puuid: str, as_of_ts: int,
                                  tier: Optional[str], division: Optional[str], lp: Optional[int]):
    con.execute(
        """
        INSERT INTO match_participant_rank(match_id, puuid, as_of_ts, tier, division, league_points)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(match_id, puuid) DO UPDATE SET
          as_of_ts=excluded.as_of_ts,
          tier=excluded.tier,
          division=excluded.division,
          league_points=excluded.league_points
        """,
        (match_id, puuid, as_of_ts, tier, division, lp),
    )


def upsert_match_tier(con: sqlite3.Connection, match_id: str, patch: str, method: str,
                      tier_label: Optional[str], tier_score: Optional[float],
                      known_cnt: int, as_of_ts: int):
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
        (match_id, patch, method, tier_label, tier_score, known_cnt, as_of_ts),
    )


def insert_match_bans(con: sqlite3.Connection, match_id: str, bans: Iterable[Tuple[int, int, int]]):
    """
    bans: iterable of (team_id, ban_slot, champ_id)
    """
    con.executemany(
        """
        INSERT OR REPLACE INTO match_bans(match_id, team_id, ban_slot, champ_id)
        VALUES(?,?,?,?)
        """,
        [(match_id, int(team_id), int(slot), int(champ_id)) for (team_id, slot, champ_id) in bans],
    )


def upsert_matchup_role(con: sqlite3.Connection, patch: str, tier: Optional[str],
                        my_role: str, enemy_role: str,
                        my_champ_id: int, enemy_champ_id: int, win: int):
    con.execute(
        """
        INSERT INTO agg_matchup_role(patch, tier, my_role, enemy_role, my_champ_id, enemy_champ_id, games, wins)
        VALUES(?,?,?,?,?,?,1,?)
        ON CONFLICT(patch, tier, my_role, enemy_role, my_champ_id, enemy_champ_id) DO UPDATE SET
          games = games + 1,
          wins  = wins + excluded.wins
        """,
        (patch, tier, my_role, enemy_role, my_champ_id, enemy_champ_id, 1 if win else 0),
    )


# --- backward compatible alias ---
def upsert_matchup(con: sqlite3.Connection, patch: str, tier: Optional[str],
                   my_role: str, enemy_role: str,
                   my_champ_id: int, enemy_champ_id: int, win: int):
    return upsert_matchup_role(
        con=con,
        patch=patch,
        tier=tier,
        my_role=my_role,
        enemy_role=enemy_role,
        my_champ_id=my_champ_id,
        enemy_champ_id=enemy_champ_id,
        win=win,
    )
