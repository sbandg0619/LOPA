# checkpoint_store.py
from __future__ import annotations

import json
import time
import sqlite3
from typing import Any, Dict, List, Set, Tuple


# ---- internal helpers ----
def _table_columns(con: sqlite3.Connection, table: str) -> List[str]:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]  # col name


def _has_table(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def ensure_state_table(con: sqlite3.Connection):
    """
    crawl_state 스키마를 '자동 감지/보강'한다.

    지원하는 2가지 형태:
    A) KV 스토어 (신규 권장)
       crawl_state(k TEXT PRIMARY KEY, v TEXT, updated_at INTEGER)

    B) 단일 row 스토어 (레거시)
       crawl_state(id INTEGER PRIMARY KEY, queue_json TEXT, visited_json TEXT, meta_json TEXT, updated_at INTEGER)
    """
    if not _has_table(con, "crawl_state"):
        # 신규 KV 스키마로 생성
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
        return

    cols = _table_columns(con, "crawl_state")

    # KV 스키마면 updated_at만 보강
    if ("k" in cols) and ("v" in cols):
        if "updated_at" not in cols:
            con.execute("ALTER TABLE crawl_state ADD COLUMN updated_at INTEGER;")
            con.commit()
        return

    # 레거시 row 스키마면 필요한 컬럼 보강
    if "id" in cols:
        need_cols = {
            "queue_json": "TEXT",
            "visited_json": "TEXT",
            "meta_json": "TEXT",
            "updated_at": "INTEGER",
        }
        for c, ctype in need_cols.items():
            if c not in cols:
                con.execute(f"ALTER TABLE crawl_state ADD COLUMN {c} {ctype};")
        # id=1 row 보장
        con.execute("INSERT OR IGNORE INTO crawl_state(id, updated_at) VALUES(1, ?)", (int(time.time()),))
        con.commit()
        return

    # 알 수 없는 스키마: 안전하게 KV로 새로 만들고 싶으면 여기서 처리할 수 있지만,
    # 일단은 명확한 에러로 알려주자.
    raise RuntimeError(f"Unknown crawl_state schema columns={cols}")


def _mode(con: sqlite3.Connection) -> str:
    cols = _table_columns(con, "crawl_state")
    if ("k" in cols) and ("v" in cols):
        return "kv"
    if "id" in cols:
        return "row"
    return "unknown"


def _kv_get(con: sqlite3.Connection, k: str) -> str | None:
    row = con.execute("SELECT v FROM crawl_state WHERE k=?", (k,)).fetchone()
    return row[0] if row else None


def _kv_set(con: sqlite3.Connection, k: str, v: str):
    ts = int(time.time())
    con.execute(
        """
        INSERT INTO crawl_state(k, v, updated_at) VALUES(?,?,?)
        ON CONFLICT(k) DO UPDATE SET v=excluded.v, updated_at=excluded.updated_at
        """,
        (k, v, ts),
    )


def _row_get(con: sqlite3.Connection) -> Tuple[str | None, str | None, str | None]:
    row = con.execute("SELECT queue_json, visited_json, meta_json FROM crawl_state WHERE id=1").fetchone()
    if not row:
        return None, None, None
    return row[0], row[1], row[2]


def _row_set(con: sqlite3.Connection, q: str, v: str, m: str):
    ts = int(time.time())
    con.execute(
        """
        INSERT INTO crawl_state(id, queue_json, visited_json, meta_json, updated_at)
        VALUES(1,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
          queue_json=excluded.queue_json,
          visited_json=excluded.visited_json,
          meta_json=excluded.meta_json,
          updated_at=excluded.updated_at
        """,
        (q, v, m, ts),
    )


# ---- public API ----
def load_state(con: sqlite3.Connection) -> Tuple[List[str], Set[str], Dict[str, Any]]:
    """
    returns: (queue_list, visited_set, meta_dict)
    """
    ensure_state_table(con)
    m = _mode(con)

    if m == "kv":
        qj = _kv_get(con, "queue_json") or "[]"
        vj = _kv_get(con, "visited_json") or "[]"
        mj = _kv_get(con, "meta_json") or "{}"
    elif m == "row":
        qj, vj, mj = _row_get(con)
        qj = qj or "[]"
        vj = vj or "[]"
        mj = mj or "{}"
    else:
        raise RuntimeError("crawl_state mode unknown")

    try:
        queue_list = list(json.loads(qj))
    except Exception:
        queue_list = []
    try:
        visited_list = list(json.loads(vj))
    except Exception:
        visited_list = []
    try:
        meta = dict(json.loads(mj))
    except Exception:
        meta = {}

    visited_set = set(str(x) for x in visited_list if x)
    queue_list = [str(x) for x in queue_list if x]
    return queue_list, visited_set, meta


def save_state(con: sqlite3.Connection, queue_list: List[str], visited_set: Set[str], meta: Dict[str, Any]):
    ensure_state_table(con)
    m = _mode(con)

    qj = json.dumps(list(queue_list or []), ensure_ascii=False)
    vj = json.dumps(list(visited_set or []), ensure_ascii=False)
    mj = json.dumps(meta or {}, ensure_ascii=False)

    if m == "kv":
        _kv_set(con, "queue_json", qj)
        _kv_set(con, "visited_json", vj)
        _kv_set(con, "meta_json", mj)
    elif m == "row":
        _row_set(con, qj, vj, mj)
    else:
        raise RuntimeError("crawl_state mode unknown")

    con.commit()


def clear_state(con: sqlite3.Connection):
    """
    queue/visited/meta를 초기화.
    """
    ensure_state_table(con)
    m = _mode(con)

    if m == "kv":
        _kv_set(con, "queue_json", "[]")
        _kv_set(con, "visited_json", "[]")
        _kv_set(con, "meta_json", "{}")
        con.commit()
        return

    if m == "row":
        _row_set(con, "[]", "[]", "{}")
        con.commit()
        return

    raise RuntimeError("crawl_state mode unknown")
