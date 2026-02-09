// web/lib/constants.js
// 목적:
// - Bridge 설정을 localStorage에 "하나의 키"로 저장/읽기
// - 배포 환경에서는 기본 bridgeBase를 비워서(=브릿지 OFF) 브릿지 없이도 웹이 동작하게 함
// - API base도 함께 저장/읽기 (env 우선, 배포 기본은 Render로 fallback)

const KEY = "lopa_bridge_config_v1";

const DEFAULT_BRIDGE_BASE_LOCAL = "http://127.0.0.1:12145";
const DEFAULT_API_BASE_LOCAL = "http://127.0.0.1:8000";

// ✅ 배포 기본 API fallback (env가 비어있을 때만 사용)
const DEFAULT_API_BASE_REMOTE = "https://lopa-api.onrender.com";

function canUseStorage() {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function isLocalhostHostname(host) {
  const h = String(host || "").trim().toLowerCase();
  return h === "localhost" || h === "127.0.0.1";
}

function defaultBridgeBase() {
  // ✅ 배포(=localhost 아님)에서는 기본 bridgeBase를 비워서 브릿지 폴링을 막는다.
  try {
    if (typeof window !== "undefined") {
      const onLocal = isLocalhostHostname(window.location.hostname || "");
      return onLocal ? DEFAULT_BRIDGE_BASE_LOCAL : "";
    }
  } catch {}
  // SSR/빌드 환경에서는 안전하게 로컬값을 반환(실제로는 클라에서 다시 결정됨)
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
  // env 우선
  const e = envApiBase();
  if (e) return e;

  // env가 비어있으면, 배포면 remote fallback / 로컬이면 local fallback
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

  // 흔한 오염 제거: 끝의 ^, 따옴표, 공백
  s = s.replace(/[\s\^"']+$/g, "");
  s = s.replace(/^["']+|["']+$/g, "");

  // 마지막 / 제거
  s = s.replace(/\/$/, "");

  if (!s) return allowEmpty ? "" : fallback;

  // http(s)만 최소 체크
  if (!(s.startsWith("http://") || s.startsWith("https://"))) return fallback;

  return s;
}

function sanitizeBase(x) {
  // ✅ 브릿지는 "비어있음"을 허용(=브릿지 OFF)
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

    // 이전 버전 호환(bridgeBase/base, bridgeToken/token)
    const bridgeBase = sanitizeBase(j?.bridgeBase ?? j?.base ?? bridgeFallback);
    const bridgeToken = sanitizeToken(j?.bridgeToken ?? j?.token ?? "");

    // apiBase 호환
    const apiBase = sanitizeApiBase(
      j?.apiBase ?? j?.api_base ?? j?.api ?? j?.API_BASE ?? apiFallback
    );

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

  // apiBase가 안 오면 기존 유지
  const api =
    typeof apiBase === "undefined"
      ? sanitizeApiBase(prev.apiBase)
      : sanitizeApiBase(apiBase);

  const payload = {
    bridgeBase: base,
    bridgeToken: token,
    apiBase: api,
    savedAt: Date.now(),
  };

  window.localStorage.setItem(KEY, JSON.stringify(payload));
}

export function clearBridgeConfig() {
  if (!canUseStorage()) return;
  window.localStorage.removeItem(KEY);
}
