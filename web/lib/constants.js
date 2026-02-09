// web/lib/constants.js
// 배포 웹에서는 기본 bridgeBase를 ""(OFF)로 둬서 브릿지 없이 동작하게 함
// 로컬(localhost)에서는 기존처럼 127 브릿지 기본값 사용
// apiBase도 같이 저장/읽기 (env 우선)

const KEY = "lopa_bridge_config_v1";

const DEFAULT_BRIDGE_BASE_LOCAL = "http://127.0.0.1:12145";

const DEFAULT_API_BASE_LOCAL = "http://127.0.0.1:8000";
const DEFAULT_API_BASE_REMOTE = "https://lopa-api.onrender.com";

function canUseStorage() {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function isLocalhostHostname(host) {
  const h = String(host || "").trim().toLowerCase();
  return h === "localhost" || h === "127.0.0.1";
}

function defaultBridgeBase() {
  try {
    if (typeof window !== "undefined") {
      const onLocal = isLocalhostHostname(window.location.hostname || "");
      return onLocal ? DEFAULT_BRIDGE_BASE_LOCAL : ""; // ✅ 배포면 브릿지 OFF
    }
  } catch {}
  return DEFAULT_BRIDGE_BASE_LOCAL;
}

function envApiBase() {
  try {
    const v =
      (typeof process !== "undefined" &&
        process.env &&
        process.env.NEXT_PUBLIC_API_BASE) ||
      "";
    return String(v || "").trim().replace(/\/$/, "");
  } catch {
    return "";
  }
}

function defaultApiBase() {
  const e = envApiBase();
  if (e) return e;

  try {
    if (typeof window !== "undefined") {
      const onLocal = isLocalhostHostname(window.location.hostname || "");
      return onLocal ? DEFAULT_API_BASE_LOCAL : DEFAULT_API_BASE_REMOTE;
    }
  } catch {}
  return DEFAULT_API_BASE_LOCAL;
}

function sanitizeUrlBase(x, fallback, { allowEmpty = false } = {}) {
  let s = String(x ?? "").trim();

  s = s.replace(/[\s\^"']+$/g, "");
  s = s.replace(/^["']+|["']+$/g, "");
  s = s.replace(/\/$/, "");

  if (!s) return allowEmpty ? "" : fallback;
  if (!(s.startsWith("http://") || s.startsWith("https://"))) return fallback;

  return s;
}

function sanitizeBase(x) {
  // ✅ 브릿지는 empty 허용(=OFF)
  return sanitizeUrlBase(x, defaultBridgeBase(), { allowEmpty: true });
}

function sanitizeApiBase(x) {
  return sanitizeUrlBase(x, defaultApiBase(), { allowEmpty: false });
}

function sanitizeToken(x) {
  return String(x ?? "").trim().replace(/^["']+|["']+$/g, "");
}

export function getBridgeConfig() {
  const bridgeFallback = defaultBridgeBase();
  const apiFallback = defaultApiBase();

  if (!canUseStorage()) {
    return { bridgeBase: bridgeFallback, bridgeToken: "", apiBase: apiFallback };
  }

  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return { bridgeBase: bridgeFallback, bridgeToken: "", apiBase: apiFallback };

    const j = JSON.parse(raw);

    const bridgeBase = sanitizeBase(j?.bridgeBase ?? j?.base ?? bridgeFallback);
    const bridgeToken = sanitizeToken(j?.bridgeToken ?? j?.token ?? "");
    const apiBase = sanitizeApiBase(j?.apiBase ?? j?.api_base ?? j?.api ?? j?.API_BASE ?? apiFallback);

    return { bridgeBase, bridgeToken, apiBase };
  } catch {
    return { bridgeBase: bridgeFallback, bridgeToken: "", apiBase: apiFallback };
  }
}

export function getBridgeBase() {
  return getBridgeConfig().bridgeBase || "";
}

export function getBridgeToken() {
  return getBridgeConfig().bridgeToken || "";
}

export function getApiBase() {
  return getBridgeConfig().apiBase || defaultApiBase();
}

export function setBridgeConfig({ bridgeBase, bridgeToken, apiBase }) {
  if (!canUseStorage()) return;

  const prev = getBridgeConfig();

  const base = sanitizeBase(typeof bridgeBase === "undefined" ? prev.bridgeBase : bridgeBase);
  const token = sanitizeToken(typeof bridgeToken === "undefined" ? prev.bridgeToken : bridgeToken);
  const api = typeof apiBase === "undefined" ? sanitizeApiBase(prev.apiBase) : sanitizeApiBase(apiBase);

  const payload = { bridgeBase: base, bridgeToken: token, apiBase: api, savedAt: Date.now() };
  window.localStorage.setItem(KEY, JSON.stringify(payload));
}

export function clearBridgeConfig() {
  if (!canUseStorage()) return;
  window.localStorage.removeItem(KEY);
}
