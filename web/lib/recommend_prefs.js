// web/lib/recommend_prefs.js
const KEY = "lopa_recommend_prefs_v1";

function canUseStorage() {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function safeParse(raw) {
  try {
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function isLocalHost() {
  if (typeof window === "undefined") return false;
  const h = String(window.location?.hostname || "");
  return h === "localhost" || h === "127.0.0.1";
}

function defaultDbPath() {
  return isLocalHost() ? "lol_graph_personal.db" : "lol_graph_public.db";
}

function asInt(x, def) {
  const n = parseInt(String(x ?? ""), 10);
  return Number.isFinite(n) ? n : def;
}

function asNum(x, def) {
  const n = Number(x);
  return Number.isFinite(n) ? n : def;
}

function asStr(x, def = "") {
  return String(x ?? def);
}

function asBool(x, def = false) {
  if (typeof x === "boolean") return x;
  const s = String(x ?? "").trim().toLowerCase();
  if (s === "1" || s === "true" || s === "yes" || s === "on") return true;
  if (s === "0" || s === "false" || s === "no" || s === "off") return false;
  return def;
}

function asObj(x, def = {}) {
  return x && typeof x === "object" && !Array.isArray(x) ? x : def;
}

export function loadRecommendPrefs() {
  if (!canUseStorage()) return null;

  const raw = window.localStorage.getItem(KEY);
  const j = safeParse(raw);
  if (!j) return null;

  // minGames: backend 검증(min>=1) 때문에 로드시에도 clamp
  const mg = Math.max(1, asInt(j.minGames, 1));
  const tn = Math.max(1, asInt(j.topN, 10));

  // minPickRatePct: 0도 유효해야 하므로 || 로 처리하지 않음
  const mpr = asNum(j.minPickRatePct, 0.5);

  return {
    dbPath: asStr(j.dbPath, defaultDbPath()),
    patch: asStr(j.patch, "ALL"),
    tier: asStr(j.tier, "ALL"),
    myRole: asStr(j.myRole, "MIDDLE"),

    candidateMode: asStr(j.candidateMode, "ALL"),
    minPickRatePct: mpr,

    // 기본은 비우는 방향(전체 후보 모드에서 의미 없음)
    champPoolText: asStr(j.champPoolText, ""),
    bansText: asStr(j.bansText, ""),
    enemyText: asStr(j.enemyText, ""),

    allyByRole: asObj(j.allyByRole, {}),
    minGames: mg,
    topN: tn,

    autoPull: asBool(j.autoPull, true),
    showAdvanced: asBool(j.showAdvanced, false),
    showRawResults: asBool(j.showRawResults, false),
    showRawState: asBool(j.showRawState, false),
  };
}

export function saveRecommendPrefs(prefs) {
  if (!canUseStorage()) return;

  const payload = {
    ...prefs,
    // 안전장치: 저장 시에도 clamp (문자열로 들어와도 OK)
    minGames: Math.max(1, parseInt(String(prefs?.minGames ?? 1), 10) || 1),
    topN: Math.max(1, parseInt(String(prefs?.topN ?? 10), 10) || 10),
    savedAt: Date.now(),
  };

  try {
    window.localStorage.setItem(KEY, JSON.stringify(payload));
  } catch {
    // ignore
  }
}

export function clearRecommendPrefs() {
  if (!canUseStorage()) return;
  window.localStorage.removeItem(KEY);
}
