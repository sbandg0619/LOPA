// web/lib/constants.js
// 목적: Bridge 설정을 localStorage에 "하나의 키"로만 저장/읽기
// + (중요) CMD escape(^) 등으로 base 끝에 쓰레기 문자가 붙는 경우 자동 정리

const KEY = "lopa_bridge_config_v1";
const DEFAULT_BASE = "http://127.0.0.1:12145";

function canUseStorage() {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function sanitizeBase(x) {
  let s = String(x || "").trim();

  // 흔한 오염 제거: 끝의 ^, 따옴표, 공백
  s = s.replace(/[\s\^"']+$/g, "");
  s = s.replace(/^["']+|["']+$/g, "");

  // 마지막 / 제거
  s = s.replace(/\/$/, "");

  return s || DEFAULT_BASE;
}

function sanitizeToken(x) {
  return String(x || "").trim().replace(/^["']+|["']+$/g, "");
}

export function getBridgeConfig() {
  if (!canUseStorage()) return { bridgeBase: DEFAULT_BASE, bridgeToken: "" };

  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return { bridgeBase: DEFAULT_BASE, bridgeToken: "" };

    const j = JSON.parse(raw);

    // 이전 버전 호환(bridgeBase/base, bridgeToken/token)
    const bridgeBase = sanitizeBase(j?.bridgeBase || j?.base || DEFAULT_BASE);
    const bridgeToken = sanitizeToken(j?.bridgeToken || j?.token || "");

    return { bridgeBase, bridgeToken };
  } catch {
    return { bridgeBase: DEFAULT_BASE, bridgeToken: "" };
  }
}

export function getBridgeBase() {
  return getBridgeConfig().bridgeBase || DEFAULT_BASE;
}

export function getBridgeToken() {
  return getBridgeConfig().bridgeToken || "";
}

export function setBridgeConfig({ bridgeBase, bridgeToken }) {
  if (!canUseStorage()) return;

  const base = sanitizeBase(bridgeBase || DEFAULT_BASE);
  const token = sanitizeToken(bridgeToken || "");

  const payload = {
    bridgeBase: base,
    bridgeToken: token,
    savedAt: Date.now(),
  };

  window.localStorage.setItem(KEY, JSON.stringify(payload));
}

export function clearBridgeConfig() {
  if (!canUseStorage()) return;
  window.localStorage.removeItem(KEY);
}
