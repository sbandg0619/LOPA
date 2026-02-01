import sqlite3

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS players (
  puuid TEXT PRIMARY KEY,
  summoner_id TEXT,
  tier TEXT,
  division TEXT,
  league_points INTEGER,
  last_rank_update INTEGER
);

CREATE TABLE IF NOT EXISTS matches (
  match_id TEXT PRIMARY KEY,
  game_creation INTEGER,
  patch TEXT,
  queue_id INTEGER
);

CREATE TABLE IF NOT EXISTS participants (
  match_id TEXT,
  puuid TEXT,
  champ_id INTEGER,
  role TEXT,
  win INTEGER,
  team_id INTEGER,
  PRIMARY KEY (match_id, puuid)
);

-- ===== 증분 집계(추천용) =====
-- (patch, tier, role, champ) 단위 games/wins
CREATE TABLE IF NOT EXISTS agg_champ_role (
  patch TEXT,
  tier TEXT,
  role TEXT,
  champ_id INTEGER,
  games INTEGER,
  wins INTEGER,
  PRIMARY KEY (patch, tier, role, champ_id)
);

-- (patch, tier, champ) 단위 role별 games 합 (P(role|champ) 계산용)
CREATE TABLE IF NOT EXISTS agg_champ_role_total (
  patch TEXT,
  tier TEXT,
  champ_id INTEGER,
  total_games INTEGER,
  PRIMARY KEY (patch, tier, champ_id)
);

-- ===== 인덱스 =====
CREATE INDEX IF NOT EXISTS idx_players_tier_div ON players(tier, division);
CREATE INDEX IF NOT EXISTS idx_part_role ON participants(role);
CREATE INDEX IF NOT EXISTS idx_part_champ ON participants(champ_id);

CREATE INDEX IF NOT EXISTS idx_agg_cr ON agg_champ_role(patch, tier, role, champ_id);
CREATE INDEX IF NOT EXISTS idx_agg_tot ON agg_champ_role_total(patch, tier, champ_id);
"""

def connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    return con

def upsert_player(con: sqlite3.Connection, puuid: str, summoner_id: str | None,
                  tier: str | None, division: str | None, lp: int | None, ts: int):
    con.execute(
        "INSERT INTO players(puuid,summoner_id,tier,division,league_points,last_rank_update) "
        "VALUES(?,?,?,?,?,?) "
        "ON CONFLICT(puuid) DO UPDATE SET "
        "summoner_id=COALESCE(excluded.summoner_id, players.summoner_id), "
        "tier=COALESCE(excluded.tier, players.tier), "
        "division=COALESCE(excluded.division, players.division), "
        "league_points=COALESCE(excluded.league_points, players.league_points), "
        "last_rank_update=excluded.last_rank_update",
        (puuid, summoner_id, tier, division, lp, ts),
    )

def insert_match(con: sqlite3.Connection, match_id: str, game_creation: int, patch: str, queue_id: int) -> bool:
    cur = con.execute(
        "INSERT OR IGNORE INTO matches(match_id,game_creation,patch,queue_id) VALUES(?,?,?,?)",
        (match_id, game_creation, patch, queue_id),
    )
    # rowcount=1이면 새로 insert 됨
    return cur.rowcount == 1

def insert_participant(con: sqlite3.Connection, match_id: str, puuid: str, champ_id: int,
                       role: str, win: int, team_id: int) -> bool:
    cur = con.execute(
        "INSERT OR IGNORE INTO participants(match_id,puuid,champ_id,role,win,team_id) VALUES(?,?,?,?,?,?)",
        (match_id, puuid, champ_id, role, win, team_id),
    )
    return cur.rowcount == 1

def upsert_agg(con: sqlite3.Connection, patch: str, tier: str | None,
               role: str, champ_id: int, win: int):
    # tier가 None이면 집계에서 제외(랭크 미상)
    if not tier:
        return
    # agg_champ_role
    con.execute(
        "INSERT INTO agg_champ_role(patch,tier,role,champ_id,games,wins) VALUES(?,?,?,?,1,?) "
        "ON CONFLICT(patch,tier,role,champ_id) DO UPDATE SET "
        "games=games+1, wins=wins+excluded.wins",
        (patch, tier, role, champ_id, int(win)),
    )
    # agg_champ_role_total
    con.execute(
        "INSERT INTO agg_champ_role_total(patch,tier,champ_id,total_games) VALUES(?,?,?,1) "
        "ON CONFLICT(patch,tier,champ_id) DO UPDATE SET total_games=total_games+1",
        (patch, tier, champ_id),
    )
