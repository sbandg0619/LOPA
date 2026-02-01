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

  return {
    dbPath: asStr(j.dbPath, "lol_graph_personal.db"),
    patch: asStr(j.patch, "ALL"),
    tier: asStr(j.tier, "ALL"),
    myRole: asStr(j.myRole, "MIDDLE"),

    // ✅ NEW
    candidateMode: asStr(j.candidateMode, "ALL"),
    minPickRatePct: asNum(j.minPickRatePct, 0.5),

    champPoolText: asStr(j.champPoolText, "103,7,61"),
    bansText: asStr(j.bansText, ""),
    enemyText: asStr(j.enemyText, ""),

    allyByRole: asObj(j.allyByRole, {}),
    minGames: asInt(j.minGames, 0),
    topN: asInt(j.topN, 10),

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
