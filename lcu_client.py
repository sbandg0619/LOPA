from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass


@dataclass
class LCUConn:
    port: int
    password: str
    protocol: str = "https"
    host: str = "127.0.0.1"

    @property
    def base_url(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}"

    @property
    def auth(self) -> Tuple[str, str]:
        return ("riot", self.password)


@dataclass
class BridgeConn:
    base_url: str
    token: str = ""


class _BridgeBackend:
    def __init__(self, conn: BridgeConn, timeout: float = 2.0):
        self.conn = conn
        self.timeout = timeout
        self._session = requests.Session()
        self._session.verify = False

    def _headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {}
        if self.conn.token:
            h["X-LOPA-TOKEN"] = self.conn.token
        return h

    def _get_json(self, path: str) -> Any:
        url = self.conn.base_url.rstrip("/") + path
        r = self._session.get(url, headers=self._headers(), timeout=self.timeout)
        if r.status_code >= 400:
            raise requests.HTTPError(f"{r.status_code} GET {path}: {r.text[:200]}")
        return r.json() if r.text else None

    def ping(self) -> Tuple[bool, str]:
        try:
            obj = self._get_json("/health")
            if isinstance(obj, dict):
                return bool(obj.get("ok")), str(obj.get("msg"))
            return True, "OK"
        except Exception as e:
            return False, str(e)

    def get_champ_select_state(self) -> Dict[str, Any]:
        obj = self._get_json("/state")
        if not isinstance(obj, dict) or not obj.get("ok"):
            return {"phase": "Unknown", "ts": int(time.time())}
        state = obj.get("state") or {}
        if not isinstance(state, dict):
            return {"phase": "Unknown", "ts": int(time.time())}
        return dict(state)


class _DirectLCUBackend:
    def __init__(self, conn: LCUConn, timeout: float = 2.0):
        self.conn = conn
        self.timeout = timeout
        self._session = requests.Session()
        self._session.verify = False
        self._session.auth = conn.auth

    def _get(self, path: str) -> Any:
        url = self.conn.base_url + path
        r = self._session.get(url, timeout=self.timeout)
        if r.status_code >= 400:
            raise requests.HTTPError(f"{r.status_code} GET {path}: {r.text[:200]}")
        return r.json() if r.text else None

    def ping(self) -> Tuple[bool, str]:
        try:
            _ = self._get("/lol-platform-config/v1/namespaces")
            return True, "OK"
        except Exception as e:
            return False, str(e)

    def get_gameflow_phase(self) -> str:
        try:
            return str(self._get("/lol-gameflow/v1/gameflow-phase"))
        except Exception:
            return "Unknown"

    def get_champ_select_session(self) -> Optional[Dict[str, Any]]:
        try:
            return self._get("/lol-champ-select/v1/session")
        except Exception:
            return None

    def get_champ_select_state(self) -> Dict[str, Any]:
        phase = self.get_gameflow_phase()
        sess = self.get_champ_select_session()

        out: Dict[str, Any] = {
            "phase": phase,
            "ts": int(time.time()),
            "localPlayerCellId": None,
            "myTeam": [],
            "theirTeam": [],
            "bans": {"myTeamBans": [], "theirTeamBans": []},
            "actionsRaw": None,
        }

        if not sess:
            return out

        out["localPlayerCellId"] = sess.get("localPlayerCellId")
        out["myTeam"] = sess.get("myTeam") or []
        out["theirTeam"] = sess.get("theirTeam") or []
        out["bans"] = sess.get("bans") or {}
        out["actionsRaw"] = sess.get("actions")
        return out


class LCUClient:
    def __init__(self, backend: Any):
        self._b = backend

    @staticmethod
    def _read_lockfile(path: str) -> LCUConn:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        parts = raw.split(":")
        if len(parts) < 5:
            raise ValueError(f"Invalid lockfile format: {raw}")
        port = int(parts[2])
        password = parts[3]
        protocol = parts[4]
        return LCUConn(port=port, password=password, protocol=protocol)

    @staticmethod
    def guess_lockfile_paths() -> List[str]:
        candidates: List[str] = []
        env_path = os.getenv("LOL_LOCKFILE")
        if env_path:
            candidates.append(env_path)

        candidates.extend([
            "C:/Riot Games/League of Legends/lockfile",
            "C:/Program Files/Riot Games/League of Legends/lockfile",
            "C:/Program Files (x86)/Riot Games/League of Legends/lockfile",
        ])

        seen = set()
        uniq = []
        for p in candidates:
            if not p or p in seen:
                continue
            seen.add(p)
            uniq.append(p)
        return uniq

    @classmethod
    def from_env_or_guess(cls, timeout: float = 2.0) -> "LCUClient":
        last_err = None
        for p in cls.guess_lockfile_paths():
            try:
                if os.path.exists(p):
                    conn = cls._read_lockfile(p)
                    return cls(_DirectLCUBackend(conn, timeout=timeout))
            except Exception as e:
                last_err = e
                continue

        raise FileNotFoundError(
            "LCU lockfile을 찾지 못했어.\n"
            "해결: .env(또는 환경변수)에 LOL_LOCKFILE=... 를 설정해줘.\n"
            '예) LOL_LOCKFILE=C:/Riot Games/League of Legends/lockfile\n'
            f"(마지막 에러: {last_err})"
        )

    def ping(self) -> Tuple[bool, str]:
        return self._b.ping()

    def get_champ_select_state(self) -> Dict[str, Any]:
        return self._b.get_champ_select_state()

    def extract_ids(self, state: Dict[str, Any]) -> Dict[str, List[int]]:
        my_picks = [p.get("championId") for p in (state.get("myTeam") or []) if int(p.get("championId") or 0) != 0]
        their_picks = [p.get("championionId") for p in (state.get("theirTeam") or []) if int(p.get("championId") or 0) != 0]

        bans = state.get("bans") or {}
        my_bans = bans.get("myTeamBans", []) or []
        their_bans = bans.get("theirTeamBans", []) or []

        def _ints(xs):
            out = []
            for x in xs or []:
                try:
                    xi = int(x)
                except Exception:
                    continue
                if xi != 0:
                    out.append(xi)
            return out

        return {
            "my_picks": _ints(my_picks),
            "their_picks": _ints(their_picks),
            "my_bans": _ints(my_bans),
            "their_bans": _ints(their_bans),
        }
