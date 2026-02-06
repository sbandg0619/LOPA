// web/lib/constants.js
// 목적: Bridge 설정을 localStorage에 "하나의 키"로만 저장/읽기
// + CMD escape(^) 등으로 base 끝에 쓰레기 문자가 붙는 경우 자동 정리
// + ✅ API base(로컬/서버)도 함께 저장해서 Recommend/API 호출이 같은 값을 보게 함

const KEY = "lopa_bridge_config_v1";
const DEFAULT_BRIDGE_BASE = "http://127.0.0.1:12145";

// ✅ 배포 기본 API는 env 우선 (없으면 로컬)
const DEFAULT_API_BASE =
  (typeof process !== "undefined" && process.env && process.env.NEXT_PUBLIC_API_BASE) ||
  "http://127.0.0.1:8000";

function canUseStorage() {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function sanitizeUrlBase(x, fallback) {
  let s = String(x || "").trim();

  // 흔한 오염 제거: 끝의 ^, 따옴표, 공백
  s = s.replace(/[\s\^"']+$/g, "");
  s = s.replace(/^["']+|["']+$/g, "");

  // 마지막 / 제거
  s = s.replace(/\/$/, "");

  // 비어있으면 fallback
  if (!s) return fallback;

  // 너무 빡세게 막지 말고 http(s)만 최소 체크
  if (!(s.startsWith("http://") || s.startsWith("https://"))) return fallback;

  return s;
}

function sanitizeBase(x) {
  return sanitizeUrlBase(x, DEFAULT_BRIDGE_BASE);
}

function sanitizeApiBase(x) {
  return sanitizeUrlBase(x, DEFAULT_API_BASE);
}

function sanitizeToken(x) {
  return String(x || "").trim().replace(/^["']+|["']+$/g, "");
}

export function getBridgeConfig() {
  if (!canUseStorage()) return { bridgeBase: DEFAULT_BRIDGE_BASE, bridgeToken: "", apiBase: DEFAULT_API_BASE };

  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return { bridgeBase: DEFAULT_BRIDGE_BASE, bridgeToken: "", apiBase: DEFAULT_API_BASE };

    const j = JSON.parse(raw);

    // 이전 버전 호환(bridgeBase/base, bridgeToken/token)
    const bridgeBase = sanitizeBase(j?.bridgeBase || j?.base || DEFAULT_BRIDGE_BASE);
    const bridgeToken = sanitizeToken(j?.bridgeToken || j?.token || "");

    // apiBase 호환
    const apiBase = sanitizeApiBase(
      j?.apiBase || j?.api_base || j?.api || j?.API_BASE || DEFAULT_API_BASE
    );

    return { bridgeBase, bridgeToken, apiBase };
  } catch {
    return { bridgeBase: DEFAULT_BRIDGE_BASE, bridgeToken: "", apiBase: DEFAULT_API_BASE };
  }
}

export function getBridgeBase() {
  return getBridgeConfig().bridgeBase || DEFAULT_BRIDGE_BASE;
}

export function getBridgeToken() {
  return getBridgeConfig().bridgeToken || "";
}

export function getApiBase() {
  return getBridgeConfig().apiBase || DEFAULT_API_BASE;
}

export function setBridgeConfig({ bridgeBase, bridgeToken, apiBase }) {
  if (!canUseStorage()) return;

  const base = sanitizeBase(bridgeBase || DEFAULT_BRIDGE_BASE);
  const token = sanitizeToken(bridgeToken || "");

  // apiBase가 안 오면 "기존 저장값"을 유지 (없으면 기본값)
  let api = DEFAULT_API_BASE;
  try {
    const prev = getBridgeConfig();
    api = prev?.apiBase || DEFAULT_API_BASE;
  } catch {}

  if (typeof apiBase !== "undefined") {
    api = sanitizeApiBase(apiBase || DEFAULT_API_BASE);
  }

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
