// web/lib/bridge.js
// - Bridge /health, /state 호출 유틸
// - https 배포 페이지에서 http://127.0.0.1 fetch가 mixed content로 막히는 문제를
//   "브릿지의 /proxy 페이지(HTTP 창) + postMessage"로 우회 지원

function safeJsonParse(txt) {
  if (!txt) return null;
  try {
    return JSON.parse(txt);
  } catch {
    return { _raw: txt };
  }
}

function baseUrl(x) {
  return String(x || "").trim().replace(/\/$/, "");
}

function mkHeaders(bridgeToken) {
  const headers = {};
  if (bridgeToken) headers["X-LOPA-TOKEN"] = String(bridgeToken).trim();
  return headers;
}

function isHttpsPage() {
  try {
    if (typeof window === "undefined") return false;
    return window.location && window.location.protocol === "https:";
  } catch {
    return false;
  }
}

function looksLikeLocalHttpBridge(bridgeBase) {
  const b = baseUrl(bridgeBase);
  return b.startsWith("http://127.0.0.1:") || b.startsWith("http://localhost:");
}

// -------------------------
// Proxy RPC (postMessage)
// -------------------------
let _proxyWin = null;
let _proxyReady = false;
let _pending = new Map(); // id -> {resolve,reject,timer}

function ensureProxyListener() {
  if (typeof window === "undefined") return;

  if (ensureProxyListener._installed) return;
  ensureProxyListener._installed = true;

  window.addEventListener("message", (ev) => {
    const data = ev.data || {};
    if (!data || data.__lopa_bridge_proxy__ !== true) return;

    const id = String(data.id || "");
    if (!id) return;

    const p = _pending.get(id);
    if (!p) return;

    clearTimeout(p.timer);
    _pending.delete(id);

    if (data.ok) p.resolve(data.res);
    else p.reject(new Error(String(data.error || "proxy error")));
  });
}

function openProxyWindow(bridgeBase) {
  ensureProxyListener();

  const proxyUrl = `${baseUrl(bridgeBase)}/proxy`;

  // 이미 살아있으면 재사용
  try {
    if (_proxyWin && !_proxyWin.closed) return _proxyWin;
  } catch {
    // ignore
  }

  // 팝업 차단 대비: window.open이 실패할 수 있음
  _proxyWin = window.open(proxyUrl, "lopa_bridge_proxy", "width=520,height=420");
  _proxyReady = Boolean(_proxyWin);

  return _proxyWin;
}

async function fetchViaProxy(path, { bridgeBase, timeoutMs = 2500 }) {
  if (typeof window === "undefined") throw new Error("proxy only available in browser");

  const w = openProxyWindow(bridgeBase);
  if (!w) {
    throw new Error("Popup blocked. Allow popups for bridge proxy window.");
  }

  const id = `p_${Date.now()}_${Math.random().toString(16).slice(2)}`;

  const prom = new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      _pending.delete(id);
      reject(new Error(`proxy timeout (${timeoutMs}ms)`));
    }, timeoutMs);

    _pending.set(id, { resolve, reject, timer });
  });

  // 메시지 전송
  w.postMessage({ __lopa_bridge_proxy__: true, id, path }, "*");
  return await prom;
}

// -------------------------
// Direct fetch (http)
// -------------------------
async function fetchBridgeDirect(path, { bridgeBase, bridgeToken, timeoutMs = 2000 }) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);

  const url = `${baseUrl(bridgeBase)}/${String(path || "").replace(/^\//, "")}`;

  try {
    const r = await fetch(url, {
      method: "GET",
      headers: mkHeaders(bridgeToken),
      signal: controller.signal,
      cache: "no-store",
    });

    const txt = await r.text();
    const j = safeJsonParse(txt) || {};

    if (r.status === 401) {
      return { ok: false, msg: "401 invalid token", status: 401, raw: j, url };
    }
    if (!r.ok) {
      return { ok: false, msg: `HTTP ${r.status}`, status: r.status, raw: j, url };
    }

    return j && typeof j === "object" ? { ...j, url } : { ok: true, data: j, url };
  } catch (e) {
    const isAbort = e?.name === "AbortError";
    const msg = isAbort ? `timeout (${timeoutMs}ms)` : String(e?.message || e);
    return { ok: false, msg, error: msg, status: 0, url };
  } finally {
    clearTimeout(id);
  }
}

// -------------------------
// Unified fetch with fallback
// -------------------------
async function fetchBridge(path, { bridgeBase, bridgeToken, timeoutMs = 2000 }) {
  const direct = await fetchBridgeDirect(path, { bridgeBase, bridgeToken, timeoutMs });

  // direct 성공/401/HTTP 에러면 그대로 반환
  if (direct && direct.ok) return direct;
  if (direct && (direct.status === 401 || (direct.status && direct.status !== 0))) return direct;

  // 네트워크 실패(status=0, Failed to fetch 등)일 때만 proxy fallback
  const needProxy = isHttpsPage() && looksLikeLocalHttpBridge(bridgeBase);
  if (!needProxy) return direct;

  try {
    const res = await fetchViaProxy(path, { bridgeBase, timeoutMs: Math.max(2500, timeoutMs) });

    // proxy 결과 표준화
    if (!res || typeof res !== "object") {
      return { ok: false, msg: "proxy invalid response", status: 0, raw: res, url: `${baseUrl(bridgeBase)}/${path}` };
    }

    const status = Number(res.status || 0);
    const body = res.body;

    if (status === 401) {
      return { ok: false, msg: "401 invalid token", status: 401, raw: body, url: res.url };
    }
    if (status && status !== 200) {
      return { ok: false, msg: `HTTP ${status}`, status, raw: body, url: res.url };
    }

    // body가 {ok:true,...} 형태
    if (body && typeof body === "object") return { ...body, url: res.url };

    return { ok: true, data: body, url: res.url };
  } catch (e) {
    return {
      ok: false,
      msg: `proxy failed: ${String(e?.message || e)}`,
      status: 0,
      url: `${baseUrl(bridgeBase)}/${String(path || "").replace(/^\//, "")}`,
    };
  }
}

export async function bridgeHealth({ bridgeBase, bridgeToken, timeoutMs = 2000 }) {
  return await fetchBridge("/health", { bridgeBase, bridgeToken, timeoutMs });
}

export async function bridgeState({ bridgeBase, bridgeToken, timeoutMs = 2000 }) {
  return await fetchBridge("/state", { bridgeBase, bridgeToken, timeoutMs });
}
