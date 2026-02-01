# lopa_bridge.py
from __future__ import annotations

import json
import os
import time
import secrets
import webbrowser
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs, urlencode

import requests
from dotenv import load_dotenv


# ---- .env load (이 파일이 있는 폴더 기준, 여러 후보를 순서대로 로드) ----
def _load_env_candidates():
    """
    우선순위:
      1) .env.<APP_PROFILE>  (예: .env.public / .env.personal)
      2) .env.personal
      3) .env.public
      4) .env
      5) 기타
    """
    here = Path(__file__).resolve().parent

    profile = (os.getenv("APP_PROFILE") or "").strip().lower()
    candidates = []
    if profile:
        candidates.append(here / f".env.{profile}")

    candidates += [
        here / ".env.personal",
        here / ".env.public",
        here / ".env",
        here / ".env.local",
        here / ".env.bridge",
    ]

    loaded = []
    for p in candidates:
        if p.exists():
            load_dotenv(dotenv_path=p, override=False)  # 먼저 로드된 값 우선
            loaded.append(str(p))
    return loaded


def _guess_lockfile_paths() -> list[str]:
    cands = [
        r"C:\Riot Games\League of Legends\lockfile",
        r"C:\Program Files\Riot Games\League of Legends\lockfile",
        r"C:\Program Files (x86)\Riot Games\League of Legends\lockfile",
    ]
    pf = os.environ.get("ProgramFiles")
    pfx = os.environ.get("ProgramFiles(x86)")
    if pf:
        cands.append(str(Path(pf) / "Riot Games" / "League of Legends" / "lockfile"))
    if pfx:
        cands.append(str(Path(pfx) / "Riot Games" / "League of Legends" / "lockfile"))
    return cands


def _read_lockfile(lockfile_path: str) -> tuple[int, str, str]:
    """
    Riot lockfile format:
      name:pid:port:password:protocol
    """
    p = Path(lockfile_path)
    if not p.exists():
        raise FileNotFoundError(f"LCU lockfile not found: {lockfile_path}")

    text = p.read_text(encoding="utf-8", errors="ignore").strip()
    parts = text.split(":")
    if len(parts) < 5:
        raise ValueError(f"Invalid lockfile format: {text}")

    port = int(parts[2])
    password = parts[3]
    protocol = parts[4]  # usually "https"
    return port, password, protocol


def _load_or_create_persistent_token(here: Path) -> str:
    """
    토큰 우선순위:
      1) env: LOPA_BRIDGE_TOKEN
      2) file: .lopa_bridge_token.txt (자동 생성/재사용)
    """
    env_token = (os.getenv("LOPA_BRIDGE_TOKEN") or "").strip()
    if env_token:
        return env_token

    token_file = here / ".lopa_bridge_token.txt"
    if token_file.exists():
        t = token_file.read_text(encoding="utf-8", errors="ignore").strip()
        if t:
            return t

    t = secrets.token_urlsafe(16)
    try:
        token_file.write_text(t, encoding="utf-8")
    except Exception:
        # 파일 저장 실패해도 동작은 하게
        pass
    return t


def _open_pairing_url(bridge_url: str, token: str):
    """
    브라우저 자동 오픈:
      - LOPA_WEB_CONNECT_URL 이 있으면 그대로 사용 (예: http://localhost:3000/connect)
      - 없으면 기본값: http://localhost:3000/connect
    query:
      ?bridge=<bridge_url>&token=<token>
    """
    connect_base = (os.getenv("LOPA_WEB_CONNECT_URL") or "http://localhost:3000/connect").strip()
    connect_base = connect_base.rstrip("/")

    q = urlencode({"bridge": bridge_url, "token": token})
    url = f"{connect_base}?{q}"

    auto = (os.getenv("LOPA_BRIDGE_AUTO_OPEN") or "1").strip().lower()
    if auto in ("0", "false", "no", "off"):
        return url

    try:
        webbrowser.open(url)
    except Exception:
        pass
    return url


class LCU:
    def __init__(self, lockfile_path: str):
        self.lockfile_path = lockfile_path

    def _auth_and_base(self) -> tuple[tuple[str, str], str]:
        port, password, protocol = _read_lockfile(self.lockfile_path)
        base = f"{protocol}://127.0.0.1:{port}"
        auth = ("riot", password)
        return auth, base

    def get(self, path: str):
        auth, base = self._auth_and_base()
        url = base + path
        r = requests.get(url, auth=auth, verify=False, timeout=2.0)

        if r.status_code != 200:
            return {"_error": f"HTTP {r.status_code}", "_text": r.text}

        try:
            return r.json()
        except Exception:
            return {"_raw": r.text}

    def ping(self) -> tuple[bool, str]:
        """
        헬스 체크는 "응답이 오면 OK"로 판단.
        """
        try:
            phase = self.get("/lol-gameflow/v1/gameflow-phase")
            if isinstance(phase, dict) and phase.get("_error"):
                return False, f"LCU error: {phase.get('_error')} {phase.get('_text','')}"
            return True, f"OK (phase={phase})"
        except Exception as e:
            return False, str(e)

    def champ_select_state(self) -> dict:
        try:
            phase = self.get("/lol-gameflow/v1/gameflow-phase")
        except Exception:
            phase = "Unknown"

        out = {"phase": str(phase)}

        if str(phase) != "ChampSelect":
            return out

        sess = self.get("/lol-champ-select/v1/session")
        if not isinstance(sess, dict) or sess.get("_error"):
            out["_error"] = sess.get("_error") if isinstance(sess, dict) else "unknown"
            out["_text"] = sess.get("_text") if isinstance(sess, dict) else ""
            return out

        out["bans"] = sess.get("bans") or {}
        out["myTeam"] = sess.get("myTeam") or []
        out["theirTeam"] = sess.get("theirTeam") or []
        out["localPlayerCellId"] = sess.get("localPlayerCellId")
        out["actionsRaw"] = sess.get("actions")  # app.py 호환용

        return out


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    server_version = "LOPABridge/0.4"

    def _send_json(self, code: int, obj: dict):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-LOPA-TOKEN")
        self.end_headers()
        self.wfile.write(data)

    def _token_ok(self) -> bool:
        need = getattr(self.server, "token", None)
        if not need:
            return True

        got = self.headers.get("X-LOPA-TOKEN")
        if got and got == need:
            return True

        try:
            q = parse_qs(urlparse(self.path).query)
            qt = (q.get("token") or [""])[0]
            return qt == need
        except Exception:
            return False

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-LOPA-TOKEN")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()

    def do_GET(self):
        if not self._token_ok():
            return self._send_json(401, {"ok": False, "error": "invalid token"})

        path = urlparse(self.path).path

        if path == "/health":
            ok, msg = self.server.lcu.ping()
            return self._send_json(200, {"ok": ok, "msg": msg, "ts": int(time.time())})

        if path == "/state":
            try:
                state = self.server.lcu.champ_select_state()
                return self._send_json(200, {"ok": True, "state": state, "ts": int(time.time())})
            except Exception as e:
                return self._send_json(500, {"ok": False, "error": str(e), "ts": int(time.time())})

        return self._send_json(404, {"ok": False, "error": "not found"})


def main():
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass

    here = Path(__file__).resolve().parent
    loaded_envs = _load_env_candidates()

    lockfile = (os.getenv("LOL_LOCKFILE") or "").strip()
    if not lockfile:
        for cand in _guess_lockfile_paths():
            if Path(cand).exists():
                lockfile = cand
                break

    if not lockfile:
        print("ERROR: LOL_LOCKFILE is missing in .env / env vars, and auto-detect failed.")
        if loaded_envs:
            print("Loaded env files:")
            for x in loaded_envs:
                print(f" - {x}")
        else:
            print("Loaded env files: (none found)  -> expected .env.public / .env.personal near lopa_bridge.py")

        print("Fix one of these:")
        print(r'  A) CMD에서 임시로 설정:  set "LOL_LOCKFILE=C:\Riot Games\League of Legends\lockfile"')
        print(r"  B) .env.public 또는 .env.personal에 추가: LOL_LOCKFILE=C:\Riot Games\League of Legends\lockfile")
        return

    host = (os.getenv("LOPA_BRIDGE_HOST") or "127.0.0.1").strip()
    port = int(os.getenv("LOPA_BRIDGE_PORT") or "12145")

    # ✅ 토큰 고정(ENV 우선, 없으면 파일 저장/재사용)
    token = _load_or_create_persistent_token(here)

    lcu = LCU(lockfile)

    httpd = ThreadedHTTPServer((host, port), Handler)
    httpd.lcu = lcu
    httpd.token = token

    bridge_url = f"http://{host}:{port}"
    pair_url = _open_pairing_url(bridge_url=bridge_url, token=token)

    print("==================================================")
    print("LOPA Bridge running")
    print(f"- APP_PROFILE : {os.getenv('APP_PROFILE')}")
    print(f"- lockfile    : {lockfile}")
    print(f"- bind        : {bridge_url}")
    print(f"- health      : {bridge_url}/health?token={token}")
    print(f"- state       : {bridge_url}/state?token={token}")
    print(f"- token       : {token}")
    print(f"- pair url    : {pair_url}")
    if loaded_envs:
        print("- loaded env  :")
        for x in loaded_envs:
            print(f"   - {x}")
    else:
        print("- loaded env  : (none)")
    print("==================================================")
    print("phase 의미:")
    print(' - "None"       : 대기(정상)')
    print(' - "Lobby/Matchmaking/ReadyCheck" : 큐 진행')
    print(' - "ChampSelect": 밴/픽 자동 읽기 가능')
    print(' - "InProgress" : 게임 중')
    print()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
