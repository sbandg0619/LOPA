# lopa_bridge.py
from __future__ import annotations

import atexit
import json
import os
import secrets
import socket
import subprocess
import sys
import time
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
        pass
    return t


def _open_pairing_url(bridge_url: str, token: str, api_url: str | None = None):
    """
    브라우저 자동 오픈:
      - LOPA_WEB_CONNECT_URL 이 있으면 그대로 사용
      - 없으면 기본값: http://localhost:3000/connect
    query:
      ?bridge=<bridge_url>&token=<token>&api=<api_url?>
    """
    connect_base = (os.getenv("LOPA_WEB_CONNECT_URL") or "http://localhost:3000/connect").strip()
    connect_base = connect_base.rstrip("/")

    qobj = {"bridge": bridge_url, "token": token}
    if api_url:
        qobj["api"] = api_url

    q = urlencode(qobj)
    url = f"{connect_base}?{q}"

    auto = (os.getenv("LOPA_BRIDGE_AUTO_OPEN") or "1").strip().lower()
    if auto in ("0", "false", "no", "off"):
        return url

    try:
        webbrowser.open(url)
    except Exception:
        pass
    return url


# -------------------------
# API auto-start helpers
# -------------------------
def _port_is_listening(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_http_ok(url: str, timeout_sec: float = 20.0, interval: float = 0.5) -> tuple[bool, str]:
    t0 = time.time()
    last_err = ""
    while time.time() - t0 < timeout_sec:
        try:
            r = requests.get(url, timeout=1.5)
            if r.status_code == 200:
                return True, "OK"
            last_err = f"HTTP {r.status_code}"
        except Exception as e:
            last_err = str(e)
        time.sleep(interval)
    return False, last_err or "timeout"


def _wait_api_meta_ready(api_url: str, timeout_sec: float = 25.0, interval: float = 0.6) -> tuple[bool, str]:
    """
    콜드스타트/초기 DB 쿼리 타이밍 문제 방지용:
    /meta 가 정상으로 latest_patch를 내줄 때까지 재시도.
    """
    meta_url = api_url.rstrip("/") + "/meta"
    t0 = time.time()
    last = ""
    while time.time() - t0 < timeout_sec:
        try:
            r = requests.get(meta_url, timeout=2.0)
            if r.status_code == 200:
                j = r.json()
                latest = str(j.get("latest_patch") or "").strip()
                ok = bool(j.get("ok"))
                if ok and latest and latest.lower() != "unknown":
                    return True, f"OK latest_patch={latest}"
                last = f"meta not ready (ok={ok}, latest_patch={latest or 'empty'})"
            else:
                last = f"HTTP {r.status_code}"
        except Exception as e:
            last = str(e)

        time.sleep(interval)

    return False, last or "timeout"


def _start_api_if_needed(here: Path) -> dict:
    """
    브릿지가 API(uvicorn)를 같이 켜는 기능.
    기본 ON. 끄려면: LOPA_API_AUTO_START=0
    """
    auto = (os.getenv("LOPA_API_AUTO_START") or "1").strip().lower()
    if auto in ("0", "false", "no", "off"):
        return {
            "enabled": False,
            "started": False,
            "url": None,
            "health_url": None,
            "msg": "LOPA_API_AUTO_START=0",
            "proc": None,
            "meta_ready": False,
        }

    host = (os.getenv("LOPA_API_HOST") or "127.0.0.1").strip()
    port = int(os.getenv("LOPA_API_PORT") or "8000")
    app = (os.getenv("LOPA_API_APP") or "api_server:app").strip()
    health_path = (os.getenv("LOPA_API_HEALTH_PATH") or "/health").strip()
    if not health_path.startswith("/"):
        health_path = "/" + health_path

    warmup_meta = (os.getenv("LOPA_API_WARMUP_META") or "1").strip().lower() not in ("0", "false", "no", "off")

    api_url = f"http://{host}:{port}"
    health_url = api_url + health_path

    if _port_is_listening(host, port):
        ok, msg = _wait_http_ok(health_url, timeout_sec=3.0, interval=0.3)
        meta_ok = False
        meta_msg = ""
        if warmup_meta and ok:
            meta_ok, meta_msg = _wait_api_meta_ready(api_url, timeout_sec=10.0, interval=0.5)
        return {
            "enabled": True,
            "started": False,
            "url": api_url,
            "health_url": health_url,
            "msg": f"port {port} already in use (api may be already running). health={ok} {msg}. meta={meta_ok} {meta_msg}".strip(),
            "proc": None,
            "meta_ready": meta_ok,
        }

    py = (os.getenv("PY") or "").strip() or sys.executable

    log_file = (os.getenv("LOPA_API_LOG_FILE") or "lopa_api.log").strip()
    log_path = here / log_file
    cmd = [py, "-m", "uvicorn", app, "--host", host, "--port", str(port)]

    try:
        lf = open(log_path, "a", encoding="utf-8", errors="ignore")
    except Exception:
        lf = None

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(here),
            stdout=lf if lf else None,
            stderr=lf if lf else None,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
    except Exception as e:
        if lf:
            try:
                lf.close()
            except Exception:
                pass
        return {
            "enabled": True,
            "started": False,
            "url": api_url,
            "health_url": health_url,
            "msg": f"FAILED to start api: {e}",
            "proc": None,
            "meta_ready": False,
        }

    def _cleanup():
        try:
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3.0)
                except Exception:
                    proc.kill()
        except Exception:
            pass
        finally:
            if lf:
                try:
                    lf.close()
                except Exception:
                    pass

    atexit.register(_cleanup)

    ok, msg = _wait_http_ok(health_url, timeout_sec=20.0, interval=0.5)

    meta_ok = False
    meta_msg = ""
    if warmup_meta and ok:
        meta_ok, meta_msg = _wait_api_meta_ready(api_url, timeout_sec=25.0, interval=0.6)

    return {
        "enabled": True,
        "started": True,
        "url": api_url,
        "health_url": health_url,
        "msg": f"started. health={ok} {msg}. meta={meta_ok} {meta_msg}. log={str(log_path)}".strip(),
        "proc": proc,
        "meta_ready": meta_ok,
    }


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
        out["actionsRaw"] = sess.get("actions")

        return out


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def _proxy_html(bridge_base: str, token: str) -> str:
    """
    https(배포) 페이지에서 http(127.0.0.1) fetch가 막히는 문제 해결용:
    - 이 페이지는 http://127.0.0.1:12145/proxy 로 열림 (same-origin http)
    - opener(https)와 postMessage로 통신하면서 /health,/state를 대신 fetch해줌
    """
    # token은 URL에 포함될 수 있으니, 여기서는 page 자체에 token을 박아둠(로컬 only)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>LOPA Bridge Proxy</title>
</head>
<body>
  <pre id="log" style="white-space:pre-wrap;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;"></pre>
<script>
(function() {{
  const TOKEN = {json.dumps(token)};
  const logEl = document.getElementById('log');
  function log(x) {{
    try {{ logEl.textContent += (String(x) + "\\n"); }} catch(e) {{}}
  }}

  // opener가 없으면 그냥 대기
  if (!window.opener) {{
    log("No opener. This page is meant to be opened by the LOPA web app.");
  }} else {{
    log("Proxy ready. Waiting for requests from opener...");
  }}

  async function doFetch(path) {{
    const url = "{bridge_base}".replace(/\\/$/, "") + "/" + String(path||"").replace(/^\\//,"");
    const r = await fetch(url, {{
      method: "GET",
      headers: TOKEN ? {{ "X-LOPA-TOKEN": TOKEN }} : {{}},
      cache: "no-store",
    }});
    const txt = await r.text();
    let j = null;
    try {{ j = txt ? JSON.parse(txt) : null; }} catch(e) {{ j = {{ _raw: txt }}; }}
    return {{ ok: r.ok, status: r.status, url, body: j }};
  }}

  window.addEventListener("message", async (ev) => {{
    // 보안: origin을 과도하게 제한하지 않되, 최소한 opener에서 온 메시지만 처리
    if (!window.opener) return;

    const data = ev.data || {{}};
    if (!data || data.__lopa_bridge_proxy__ !== true) return;

    const id = String(data.id || "");
    const path = String(data.path || "");
    if (!id || !path) return;

    try {{
      const res = await doFetch(path);
      window.opener.postMessage({{
        __lopa_bridge_proxy__ : true,
        id,
        ok: true,
        res,
      }}, "*");
    }} catch (e) {{
      window.opener.postMessage({{
        __lopa_bridge_proxy__ : true,
        id,
        ok: false,
        error: String(e && e.message ? e.message : e),
      }}, "*");
    }}
  }});
}})();
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "LOPABridge/0.7"

    def _send_json(self, code: int, obj: dict):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-LOPA-TOKEN")
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, code: int, html: str):
        data = html.encode("utf-8", errors="ignore")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
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
        path = urlparse(self.path).path

        # ✅ mixed content 우회용 proxy 페이지는 토큰 검사 전에 제공(로컬에서만 열리므로)
        # (proxy 페이지 내부 fetch는 헤더로 토큰을 붙여서 /health,/state를 호출함)
        if path == "/proxy":
            bridge_base = getattr(self.server, "bridge_url", "http://127.0.0.1:12145")
            token = getattr(self.server, "token", "")
            return self._send_html(200, _proxy_html(bridge_base=bridge_base, token=token))

        if not self._token_ok():
            return self._send_json(401, {"ok": False, "error": "invalid token"})

        if path == "/health":
            ok, msg = self.server.lcu.ping()
            return self._send_json(200, {"ok": ok, "msg": msg, "ts": int(time.time())})

        if path == "/api_health":
            info = getattr(self.server, "api_info", {}) or {}
            health_url = info.get("health_url")
            if not health_url:
                return self._send_json(200, {"ok": False, "msg": "api not configured", "ts": int(time.time())})

            try:
                r = requests.get(health_url, timeout=1.5)
                return self._send_json(
                    200,
                    {
                        "ok": r.status_code == 200,
                        "msg": "OK" if r.status_code == 200 else f"HTTP {r.status_code}",
                        "api_url": info.get("url"),
                        "health_url": health_url,
                        "meta_ready": bool(info.get("meta_ready", False)),
                        "ts": int(time.time()),
                    },
                )
            except Exception as e:
                return self._send_json(
                    200,
                    {
                        "ok": False,
                        "msg": str(e),
                        "api_url": info.get("url"),
                        "health_url": health_url,
                        "meta_ready": bool(info.get("meta_ready", False)),
                        "ts": int(time.time()),
                    },
                )

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

    # 0) API 먼저 자동 실행 + /meta 워밍업
    api_info = _start_api_if_needed(here)

    # 1) lockfile 찾기
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

    token = _load_or_create_persistent_token(here)
    lcu = LCU(lockfile)

    httpd = ThreadedHTTPServer((host, port), Handler)
    httpd.lcu = lcu
    httpd.token = token
    httpd.api_info = api_info

    bridge_url = f"http://{host}:{port}"
    httpd.bridge_url = bridge_url  # ✅ proxy html이 base를 알 수 있게

    pair_url = _open_pairing_url(bridge_url=bridge_url, token=token, api_url=api_info.get("url"))

    print("==================================================")
    print("LOPA Bridge running")
    print(f"- APP_PROFILE : {os.getenv('APP_PROFILE')}")
    print(f"- lockfile    : {lockfile}")
    print(f"- bind        : {bridge_url}")
    print(f"- health      : {bridge_url}/health?token={token}")
    print(f"- state       : {bridge_url}/state?token={token}")
    print(f"- proxy       : {bridge_url}/proxy   (for https mixed-content bypass)")
    print(f"- api_health  : {bridge_url}/api_health?token={token}")
    print(f"- token       : {token}")
    print(f"- pair url    : {pair_url}")
    print(f"- api auto    : enabled={api_info.get('enabled')} started={api_info.get('started')} url={api_info.get('url')}")
    print(f"- api meta    : meta_ready={api_info.get('meta_ready')}")
    print(f"- api msg     : {api_info.get('msg')}")
    if loaded_envs:
        print("- loaded env  :")
        for x in loaded_envs:
            print(f"   - {x}")
    else:
        print("- loaded env  : (none)")
    print("==================================================")
    print()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
