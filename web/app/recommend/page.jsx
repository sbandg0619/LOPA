"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { bridgeHealth, bridgeState } from "../../lib/bridge";
import { getBridgeBase, getBridgeToken, getBridgeConfig } from "../../lib/constants";
import { apiMeta, apiRecommend } from "../../lib/api";
import { useChampionCatalog } from "../../lib/champs";
import { loadRecommendPrefs, saveRecommendPrefs, clearRecommendPrefs } from "../../lib/recommend_prefs";

const ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"];

const ROLE_KO = {
  TOP: "탑",
  JUNGLE: "정글",
  MIDDLE: "미드",
  BOTTOM: "원딜",
  UTILITY: "서폿",
};

const TIERS = [
  "ALL",
  "IRON",
  "BRONZE",
  "SILVER",
  "GOLD",
  "PLATINUM",
  "EMERALD",
  "DIAMOND",
  "MASTER",
  "GRANDMASTER",
  "CHALLENGER",
];

function norm(s) {
  return String(s || "")
    .trim()
    .toLowerCase()
    .replace(/[ \.\-_'’_·]/g, "");
}

function editDistance(a, b) {
  const s = a || "";
  const t = b || "";
  const n = s.length;
  const m = t.length;
  if (!n) return m;
  if (!m) return n;
  const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = 0; i <= n; i++) dp[i][0] = i;
  for (let j = 0; j <= m; j++) dp[0][j] = j;
  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= m; j++) {
      const cost = s[i - 1] === t[j - 1] ? 0 : 1;
      dp[i][j] = Math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost);
    }
  }
  return dp[n][m];
}

function parseIds(text) {
  const s = String(text || "").trim();
  if (!s) return [];
  const out = [];
  for (const part of s.split(/[,\s]+/)) {
    const n = parseInt(part, 10);
    if (Number.isFinite(n) && n !== 0 && !out.includes(n)) out.push(n);
  }
  return out;
}

function idsToText(ids) {
  return (ids || []).join(",");
}

function safeJsonParse(txt) {
  try {
    return JSON.parse(txt || "{}");
  } catch {
    return {};
  }
}

function emptyAlly() {
  return { TOP: [], JUNGLE: [], MIDDLE: [], BOTTOM: [], UTILITY: [] };
}

function sanitizeAlly(obj) {
  const out = emptyAlly();
  for (const [k, v] of Object.entries(obj || {})) {
    const kk = String(k || "").toUpperCase();
    if (!ROLES.includes(kk)) continue;
    if (Array.isArray(v)) {
      out[kk] = v
        .map((x) => parseInt(x, 10))
        .filter((n) => Number.isFinite(n) && n !== 0)
        .filter((n, i, arr) => arr.indexOf(n) === i);
    }
  }
  return out;
}

/**
 * ✅ pick_rate 표시 유틸
 */
function formatPickRate(rec) {
  if (!rec || typeof rec !== "object") return "(n/a)";

  const candidates = [
    rec.pick_rate,
    rec.pick_rate_pct,
    rec.pickRate,
    rec.pickRatePct,
    rec.pick_rate_percent,
    rec.pickRatePercent,
    rec.pr,
  ];

  let v = null;
  for (const x of candidates) {
    if (x === null || typeof x === "undefined") continue;
    const n = Number(x);
    if (Number.isFinite(n)) {
      v = n;
      break;
    }
  }

  if (v === null) {
    const g = Number(rec.games);
    const tg =
      Number(rec.total_games) ||
      Number(rec.totalGames) ||
      Number(rec.role_games_total) ||
      Number(rec.roleGamesTotal);

    if (Number.isFinite(g) && Number.isFinite(tg) && tg > 0) {
      v = g / tg;
    }
  }

  if (v === null) return "(n/a)";

  let pct = v;
  if (pct >= 0 && pct <= 1.0000001) pct = pct * 100;
  if (!Number.isFinite(pct)) return "(n/a)";
  return pct.toFixed(2);
}

function Chip({ label, onRemove }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        padding: "6px 10px",
        borderRadius: 999,
        border: "1px solid var(--line)",
        background: "rgba(255,255,255,0.04)",
        fontWeight: 800,
        marginRight: 8,
        marginBottom: 8,
      }}
    >
      <span>{label}</span>
      {onRemove ? (
        <button className="btn" onClick={onRemove} style={{ padding: "4px 8px", borderRadius: 999, fontWeight: 900 }}>
          ×
        </button>
      ) : null}
    </span>
  );
}

function renderIdChips({ ids, idToName, onRemove }) {
  if (!ids || !ids.length) return <div className="p">(비어있음)</div>;
  return (
    <div style={{ marginTop: 6 }}>
      {ids.map((cid) => (
        <Chip key={cid} label={`${idToName?.[cid] || "UNKNOWN"} (${cid})`} onRemove={onRemove ? () => onRemove(cid) : null} />
      ))}
    </div>
  );
}

function resolveChampionIdByName(input, { nameToId, normToId }) {
  const q = String(input || "").trim();
  if (!q) return { id: null, candidates: [] };

  // 1) 숫자 입력이면 id로 처리
  const asNum = parseInt(q, 10);
  if (Number.isFinite(asNum) && asNum !== 0) return { id: asNum, candidates: [] };

  // 2) exact name
  if (nameToId && nameToId[q]) return { id: parseInt(nameToId[q], 10), candidates: [] };

  // 3) normalized exact
  const nq = norm(q);
  if (normToId && normToId[nq]) return { id: normToId[nq], candidates: [] };

  const norms = Object.keys(normToId || {});
  if (!norms.length) return { id: null, candidates: [] };

  const scored = norms
    .map((k) => {
      const contains = k.includes(nq) || nq.includes(k) ? -2 : 0;
      const starts = k.startsWith(nq) || nq.startsWith(k) ? -2 : 0;
      const d = editDistance(nq, k);
      return { k, score: d + contains + starts };
    })
    .sort((a, b) => a.score - b.score)
    .slice(0, 5);

  const cands = scored
    .map((x) => normToId[x.k])
    .filter((cid, i, arr) => Number.isFinite(cid) && arr.indexOf(cid) === i);

  return { id: null, candidates: cands };
}

function Metric({ k, v, hint }) {
  return (
    <div style={{ padding: "8px 10px", borderRadius: 12, border: "1px solid var(--line)", background: "rgba(255,255,255,0.03)" }}>
      <div className="p" style={{ margin: 0, fontWeight: 900, color: "var(--text)" }} title={hint || ""}>
        {k}
      </div>
      <div style={{ fontWeight: 900, fontSize: 18, marginTop: 4 }}>{v}</div>
    </div>
  );
}

function ScoreBar({ value }) {
  const v = Number(value);
  const pct = Number.isFinite(v) ? Math.max(0, Math.min(120, v)) : 0;
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ height: 10, borderRadius: 999, border: "1px solid var(--line)", overflow: "hidden", background: "rgba(255,255,255,0.04)" }}>
        <div style={{ width: `${(pct / 120) * 100}%`, height: "100%", background: "rgba(120,140,255,0.55)" }} />
      </div>
      <div className="p" style={{ marginTop: 6, fontSize: 12 }}>
        score scale: 0~120(clamp)
      </div>
    </div>
  );
}

/** actionsRaw: [[{...}]] 형태를 안전하게 flat */
function flattenActions(actionsRaw) {
  const out = [];
  if (!Array.isArray(actionsRaw)) return out;
  for (const turn of actionsRaw) {
    if (!Array.isArray(turn)) continue;
    for (const a of turn) {
      if (a && typeof a === "object") out.push(a);
    }
  }
  return out;
}

function posToRole(assignedPosition) {
  const pos = String(assignedPosition || "").toLowerCase();
  const map = {
    top: "TOP",
    jungle: "JUNGLE",
    middle: "MIDDLE",
    mid: "MIDDLE",
    bottom: "BOTTOM",
    bot: "BOTTOM",
    utility: "UTILITY",
    support: "UTILITY",
    sup: "UTILITY",
  };
  return map[pos] || "";
}

/**
 * ✅ "확정(completed)된 밴/픽"만 뽑아내는 extractor
 * - hover(바꾸는 중) championId는 반영 안 함
 * - actionsRaw가 없으면 fallback(old 방식)
 */
function extractConfirmedFromState(state) {
  const actions = flattenActions(state?.actionsRaw || state?.actions || []);
  const banActions = actions.filter((a) => String(a?.type || "") === "ban");
  const pickActions = actions.filter((a) => String(a?.type || "") === "pick");

  const completedBanActions = banActions.filter((a) => a?.completed === true);
  const completedPickActions = pickActions.filter((a) => a?.completed === true);

  const banTotal = banActions.length;
  const completedBanCount = completedBanActions.length;
  const bansComplete = banTotal > 0 && completedBanCount === banTotal;

  const pickTotal = pickActions.length;
  const completedPickCount = completedPickActions.length;

  // 확정 ban champIds
  const bans = [];
  for (const a of completedBanActions) {
    const cid = parseInt(a?.championId || 0, 10);
    if (Number.isFinite(cid) && cid !== 0 && !bans.includes(cid)) bans.push(cid);
  }

  // 확정 pick: cellId -> champId
  const pickByCellId = {};
  for (const a of completedPickActions) {
    const cid = parseInt(a?.championId || 0, 10);
    const cell = parseInt(a?.actorCellId ?? -1, 10);
    if (!Number.isFinite(cid) || cid === 0) continue;
    if (!Number.isFinite(cell) || cell < 0) continue;
    pickByCellId[cell] = cid;
  }

  // 팀별 확정 pick 목록 구성
  const enemy = [];
  const allyByRole = { TOP: [], JUNGLE: [], MIDDLE: [], BOTTOM: [], UTILITY: [] };

  for (const p of state?.theirTeam || []) {
    const cell = parseInt(p?.cellId ?? -1, 10);
    const cid = Number.isFinite(cell) ? pickByCellId[cell] : 0;
    if (Number.isFinite(cid) && cid !== 0 && !enemy.includes(cid)) enemy.push(cid);
  }

  for (const p of state?.myTeam || []) {
    const cell = parseInt(p?.cellId ?? -1, 10);
    const cid = Number.isFinite(cell) ? pickByCellId[cell] : 0;
    if (!Number.isFinite(cid) || cid === 0) continue;

    const role = posToRole(p?.assignedPosition);
    if (role && !allyByRole[role].includes(cid)) allyByRole[role].push(cid);
  }

  // 내 픽 확정 여부
  const myCell = parseInt(state?.localPlayerCellId ?? -1, 10);
  const myPickId = Number.isFinite(myCell) ? (pickByCellId[myCell] || 0) : 0;
  const myPickLocked = Number.isFinite(myPickId) && myPickId !== 0;

  return {
    bans,
    enemy,
    allyByRole,
    banTotal,
    completedBanCount,
    bansComplete,
    pickTotal,
    completedPickCount,
    myPickLocked,
    myPickId,
  };
}

export default function RecommendPage() {
  const [bridgeBase, setBridgeBase] = useState("");
  const [bridgeToken, setBridgeToken] = useState("");

  const [bridgeOk, setBridgeOk] = useState(false);
  const [bridgeMsg, setBridgeMsg] = useState("");
  const [phase, setPhase] = useState("Unknown");
  const [lastState, setLastState] = useState(null);

  const [autoPull, setAutoPull] = useState(true);

  // ✅ 입력 모드(기본 자동/브릿지)
  const [manualInput, setManualInput] = useState(false);

  // ✅ NEW: 자동 추천(확정 이벤트 기반)
  const [autoRecommend, setAutoRecommend] = useState(true);
  const [autoRecMsg, setAutoRecMsg] = useState("");

  const DEFAULT_DB_PATH =
    typeof window !== "undefined" && (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1")
      ? "lol_graph_personal.db"
      : "lol_graph_public.db";

  const [dbPath, setDbPath] = useState(DEFAULT_DB_PATH);
  const [patch, setPatch] = useState("ALL");
  const [tier, setTier] = useState("ALL");
  const [myRole, setMyRole] = useState("MIDDLE");

  const [candidateMode, setCandidateMode] = useState("ALL");
  const [minPickRatePct, setMinPickRatePct] = useState(0.5);

  const [metaLoading, setMetaLoading] = useState(false);
  const [metaErr, setMetaErr] = useState("");
  const [availablePatches, setAvailablePatches] = useState([]);
  const [latestPatch, setLatestPatch] = useState("");

  const [champPoolText, setChampPoolText] = useState("103,7,61");
  const [bansText, setBansText] = useState("");
  const [enemyText, setEnemyText] = useState("");

  const [allyByRole, setAllyByRole] = useState(() => emptyAlly());
  const [allyJsonText, setAllyJsonText] = useState(() => JSON.stringify(emptyAlly()));

  const [minGames, setMinGames] = useState(1);
  const [topN, setTopN] = useState(10);

  const [recs, setRecs] = useState([]);
  const [apiRaw, setApiRaw] = useState(null);
  const [apiErr, setApiErr] = useState("");
  const [apiRunning, setApiRunning] = useState(false);
  const [lastRunAt, setLastRunAt] = useState("");

  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showRawResults, setShowRawResults] = useState(false);
  const [showRawState, setShowRawState] = useState(false);

  const { ready: catReady, status: catStatus, idToName, nameToId } = useChampionCatalog();

  const normToId = useMemo(() => {
    const out = {};
    if (!nameToId) return out;
    for (const [nm, cid] of Object.entries(nameToId)) {
      const k = norm(nm);
      const n = parseInt(cid, 10);
      if (k && Number.isFinite(n) && n !== 0) out[k] = n;
    }
    return out;
  }, [nameToId]);

  const healthInFlightRef = useRef(false);
  const stateInFlightRef = useRef(false);

  const prefsLoadedRef = useRef(false);

  // ✅ 자동추천 상태(폴링 중 중복 호출 방지)
  const autoRecInFlightRef = useRef(false);
  const autoRecDoneRef = useRef(false); // 내 픽 확정 후 true => 이후 자동추천 stop
  const prevBanCompleteRef = useRef(false);
  const prevCompletedPickCountRef = useRef(0);
  const lastAutoSigRef = useRef(""); // 동일 상태 연타 방지

  useEffect(() => {
    if (prefsLoadedRef.current) return;
    prefsLoadedRef.current = true;

    const p = loadRecommendPrefs();
    if (!p) return;

    if (p.dbPath) setDbPath(p.dbPath);
    if (p.patch) setPatch(p.patch);
    if (p.tier) setTier(p.tier);
    if (p.myRole) setMyRole(p.myRole);

    if (typeof p.champPoolText === "string") setChampPoolText(p.champPoolText);
    if (typeof p.bansText === "string") setBansText(p.bansText);
    if (typeof p.enemyText === "string") setEnemyText(p.enemyText);

    const ally2 = sanitizeAlly(p.allyByRole || emptyAlly());
    setAllyByRole(ally2);
    setAllyJsonText(JSON.stringify(ally2));

    const mg = Math.max(1, Number(p.minGames) || 1);
    setMinGames(mg);

    setTopN(Number(p.topN) || 10);

    setAutoPull(Boolean(p.autoPull));
    setShowAdvanced(Boolean(p.showAdvanced));
    setShowRawResults(Boolean(p.showRawResults));
    setShowRawState(Boolean(p.showRawState));

    if (p.candidateMode) setCandidateMode(String(p.candidateMode));
    if (typeof p.minPickRatePct !== "undefined") setMinPickRatePct(Number(p.minPickRatePct) || 0.5);

    setManualInput(Boolean(p.manualInput));
    setAutoRecommend(Boolean(p.autoRecommend));
  }, []);

  const saveTimerRef = useRef(null);
  useEffect(() => {
    if (!prefsLoadedRef.current) return;

    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      saveRecommendPrefs({
        dbPath,
        patch,
        tier,
        myRole,
        candidateMode,
        minPickRatePct,
        champPoolText,
        bansText,
        enemyText,
        allyByRole,
        minGames: Math.max(1, Number(minGames) || 1),
        topN: Math.max(1, Number(topN) || 10),
        autoPull,
        manualInput,
        autoRecommend,
        showAdvanced,
        showRawResults,
        showRawState,
      });
    }, 400);

    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, [
    dbPath,
    patch,
    tier,
    myRole,
    candidateMode,
    minPickRatePct,
    champPoolText,
    bansText,
    enemyText,
    allyByRole,
    minGames,
    topN,
    autoPull,
    manualInput,
    autoRecommend,
    showAdvanced,
    showRawResults,
    showRawState,
  ]);

  function reloadBridgeConfig({ showMsg = false } = {}) {
    let base = "";
    let token = "";
    try {
      if (typeof getBridgeConfig === "function") {
        const cfg = getBridgeConfig();
        base = cfg?.bridgeBase || "";
        token = cfg?.bridgeToken || "";
      } else {
        base = getBridgeBase();
        token = getBridgeToken();
      }
    } catch {
      base = getBridgeBase();
      token = getBridgeToken();
    }

    setBridgeBase(base);
    setBridgeToken(token);

    if (showMsg) {
      const b = String(base || "").trim().replace(/\/$/, "");
      const t = String(token || "").trim();
      setBridgeMsg(`reloaded from localStorage (base=${b || "(empty)"}, token=${t ? "set" : "empty"})`);
    }
  }

  useEffect(() => {
    reloadBridgeConfig({ showMsg: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    function onFocus() {
      reloadBridgeConfig({ showMsg: false });
    }
    function onVis() {
      if (document.visibilityState === "visible") reloadBridgeConfig({ showMsg: false });
    }
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVis);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    function onStorage() {
      reloadBridgeConfig({ showMsg: false });
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const effectiveBase = useMemo(() => (bridgeBase || "").trim().replace(/\/$/, ""), [bridgeBase]);
  const effectiveToken = useMemo(() => (bridgeToken || "").trim(), [bridgeToken]);

  const BRIDGE_TIMEOUT_MS = 3500;
  const STATE_POLL_MS = 1200;
  const HEALTH_POLL_MS = 8000;

  async function refreshBridgeHealth({ silent = false } = {}) {
    if (!effectiveBase) {
      setBridgeOk(false);
      setBridgeMsg("bridgeBase is empty");
      return null;
    }

    if (healthInFlightRef.current) return null;
    healthInFlightRef.current = true;

    try {
      const j = await bridgeHealth({
        bridgeBase: effectiveBase,
        bridgeToken: effectiveToken,
        timeoutMs: BRIDGE_TIMEOUT_MS,
      });

      const ok = Boolean(j?.ok);
      setBridgeOk(ok);

      if (!ok && String(j?.msg || "").includes("401")) {
        setBridgeMsg("401 invalid token (Connect에서 저장 후, 이 탭으로 돌아오면 자동 반영됨)");
      } else {
        setBridgeMsg(String(j?.msg || j?.error || ""));
      }

      return j;
    } catch (e) {
      setBridgeOk(false);
      if (!silent) setBridgeMsg(String(e));
      return null;
    } finally {
      healthInFlightRef.current = false;
    }
  }

  const champPoolIds = useMemo(() => parseIds(champPoolText), [champPoolText]);
  const bansIds = useMemo(() => parseIds(bansText), [bansText]);
  const enemyIds = useMemo(() => parseIds(enemyText), [enemyText]);

  function addIdToText(setter, currentText, cid) {
    const ids = parseIds(currentText);
    if (!ids.includes(cid)) ids.push(cid);
    setter(idsToText(ids));
  }

  function removeIdFromText(setter, currentText, cid) {
    const ids = parseIds(currentText).filter((x) => x !== cid);
    setter(idsToText(ids));
  }

  // ===== 수동 입력 UI(이름으로 추가) =====
  const [poolName, setPoolName] = useState("");
  const [banName, setBanName] = useState("");
  const [enemyName, setEnemyName] = useState("");
  const [allyNameByRole, setAllyNameByRole] = useState(() => ({ TOP: "", JUNGLE: "", MIDDLE: "", BOTTOM: "", UTILITY: "" }));

  // nameHints: { kind: "pool"|"bans"|"enemy"|"ally", role?: "TOP"... , cands: [id...] }
  const [nameHints, setNameHints] = useState({ kind: "", role: "", cands: [] });

  function applyHintPick(kind, cid, role = "") {
    setNameHints({ kind: "", role: "", cands: [] });

    if (kind === "pool") addIdToText(setChampPoolText, champPoolText, cid);
    if (kind === "bans") addIdToText(setBansText, bansText, cid);
    if (kind === "enemy") addIdToText(setEnemyText, enemyText, cid);

    if (kind === "ally" && role && ROLES.includes(role)) {
      setAllyByRole((prev) => {
        const next = { ...prev };
        const arr = Array.isArray(next[role]) ? [...next[role]] : [];
        if (!arr.includes(cid)) arr.push(cid);
        next[role] = arr;
        return next;
      });
    }
  }

  function renderHints() {
    if (!nameHints?.cands?.length) return null;

    const title =
      nameHints.kind === "pool"
        ? "Champ Pool 후보"
        : nameHints.kind === "bans"
        ? "Bans 후보"
        : nameHints.kind === "enemy"
        ? "Enemy 후보"
        : nameHints.kind === "ally"
        ? `Ally 후보 (${nameHints.role})`
        : "이름 후보";

    return (
      <div className="card" style={{ marginTop: 10 }}>
        <div className="h2">{title}</div>
        <div className="p">정확히 매칭이 안돼서 후보를 띄웠음. 하나 클릭하면 추가됨.</div>
        <div style={{ marginTop: 8 }} className="row">
          {nameHints.cands.map((cid) => (
            <button key={`hint_btn_${cid}`} className="btn" onClick={() => applyHintPick(nameHints.kind, cid, nameHints.role)}>
              {idToName?.[cid] || `UNKNOWN (${cid})`}
            </button>
          ))}
          <button className="btn" onClick={() => setNameHints({ kind: "", role: "", cands: [] })}>
            닫기
          </button>
        </div>
      </div>
    );
  }

  function addByNameOrHint({ kind, role, input, clearInput, addByIdFallback }) {
    const txt = String(input || "").trim();
    if (!txt) return;

    const { id, candidates } = resolveChampionIdByName(txt, { nameToId, normToId });
    if (id) {
      addByIdFallback(id);
      clearInput("");
      return;
    }
    if (candidates?.length) {
      setNameHints({ kind, role: role || "", cands: candidates });
      return;
    }
  }

  async function runRecommendWith({ bansIdsOverride, enemyIdsOverride, allyByRoleOverride, reason = "" } = {}) {
    if (autoRecInFlightRef.current) return;
    autoRecInFlightRef.current = true;

    setApiRunning(true);
    setLastRunAt(new Date().toLocaleTimeString());
    setApiErr("");
    setApiRaw(null);
    setRecs([]);

    // POOL 모드 방어
    if (candidateMode === "POOL" && !champPoolIds.length) {
      setApiErr("POOL 모드인데 champ_pool이 비어있음 (내 챔프폭을 최소 1개 추가해야 함)");
      setApiRunning(false);
      autoRecInFlightRef.current = false;
      return;
    }

    const minPickRate = Math.max(0, Number(minPickRatePct) || 0) / 100.0;

    const body = {
      db_path: dbPath,
      patch,
      tier,
      my_role: myRole,
      use_champ_pool: candidateMode === "POOL",
      champ_pool: candidateMode === "POOL" ? champPoolIds : [],
      bans: Array.isArray(bansIdsOverride) ? bansIdsOverride : bansIds,
      enemy_picks: Array.isArray(enemyIdsOverride) ? enemyIdsOverride : enemyIds,
      ally_picks_by_role: allyByRoleOverride ? allyByRoleOverride : allyByRole,
      min_games: Math.max(1, Number(minGames) || 1),
      min_pick_rate: minPickRate,
      top_n: Math.max(1, Number(topN) || 10),
      max_candidates: 400,
    };

    try {
      const j = await apiRecommend(body);
      setApiRaw(j);
      setRecs(Array.isArray(j?.recs) ? j.recs : []);
      if (!Array.isArray(j?.recs)) {
        setApiErr("API 응답에 recs가 없음(형식 이상) — Raw API를 확인하세요.");
      }
      if (reason) setAutoRecMsg(`✅ auto recommend: ${reason}`);
    } catch (e) {
      let msg = "";
      try {
        if (e && typeof e === "object") {
          if (typeof e.message === "string" && e.message.trim()) msg = e.message;
          else msg = JSON.stringify(e, null, 2);
        } else {
          msg = String(e);
        }
      } catch {
        msg = String(e);
      }
      setApiErr(msg);
      if (reason) setAutoRecMsg(`❌ auto recommend failed: ${reason}`);
    } finally {
      setApiRunning(false);
      autoRecInFlightRef.current = false;
    }
  }

  async function runRecommend() {
    return await runRecommendWith({ reason: "" });
  }

  function resetAutoRecSession() {
    autoRecDoneRef.current = false;
    prevBanCompleteRef.current = false;
    prevCompletedPickCountRef.current = 0;
    lastAutoSigRef.current = "";
    setAutoRecMsg("");
  }

  async function pullBridgeStateOnce() {
    if (!effectiveBase) return;
    if (stateInFlightRef.current) return;
    stateInFlightRef.current = true;

    try {
      const j = await bridgeState({
        bridgeBase: effectiveBase,
        bridgeToken: effectiveToken,
        timeoutMs: BRIDGE_TIMEOUT_MS,
      });

      if (j && j.ok && j.state) {
        setLastState(j.state);
        const nextPhase = j.state.phase || "Unknown";
        setPhase(nextPhase);

        // ChampSelect 밖으로 나가면 자동추천 세션 리셋
        if (String(nextPhase) !== "ChampSelect") {
          resetAutoRecSession();
        }

        // ✅ 자동 입력 모드에서만 "확정된 값"으로 bans/enemy/ally 갱신
        if (!manualInput) {
          const ex = extractConfirmedFromState(j.state);

          // UI 반영(확정된 값만)
          setBansText(idsToText(ex.bans));
          setEnemyText(idsToText(ex.enemy));
          const ally2 = sanitizeAlly(ex.allyByRole);
          setAllyByRole(ally2);
          setAllyJsonText(JSON.stringify(ally2));

          // ✅ 자동추천 트리거
          const canAuto =
            autoRecommend &&
            autoPull &&
            !manualInput &&
            String(nextPhase) === "ChampSelect" &&
            !autoRecDoneRef.current &&
            !autoRecInFlightRef.current;

          if (canAuto) {
            // 동일 상태 연타 방지용 signature
            const sig = `B:${ex.bans.slice().sort((a, b) => a - b).join(",")}|E:${ex.enemy
              .slice()
              .sort((a, b) => a - b)
              .join(",")}|P:${ex.completedPickCount}|BC:${ex.bansComplete ? 1 : 0}|MY:${ex.myPickId || 0}`;

            // 트리거 조건:
            // 1) bansComplete가 false->true 되는 순간 1회
            // 2) completedPickCount가 증가할 때마다 1회
            // 3) 내 픽이 확정되는 순간: 그 1회 추천 후 자동추천 종료
            const banJustCompleted = ex.bansComplete && !prevBanCompleteRef.current;
            const pickIncreased = ex.completedPickCount > (prevCompletedPickCountRef.current || 0);

            // refs 업데이트는 아래에서
            let shouldFire = false;
            let reason = "";

            if (banJustCompleted) {
              shouldFire = true;
              reason = "bans completed";
            } else if (pickIncreased) {
              shouldFire = true;
              reason = "pick locked";
            }

            // 같은 시그니처로 연속 호출 방지
            if (shouldFire && sig === lastAutoSigRef.current) {
              shouldFire = false;
            }

            if (shouldFire) {
              lastAutoSigRef.current = sig;

              // 추천 호출은 "ex로 만든 확정값"으로 바로 호출(레이스 방지)
              await runRecommendWith({
                bansIdsOverride: ex.bans,
                enemyIdsOverride: ex.enemy,
                allyByRoleOverride: ally2,
                reason,
              });

              // 내 픽 확정이면 여기서 자동추천 종료
              if (ex.myPickLocked) {
                autoRecDoneRef.current = true;
                setAutoRecMsg("✅ auto recommend stopped (my pick locked)");
              }
            }

            // refs update
            prevBanCompleteRef.current = Boolean(ex.bansComplete);
            prevCompletedPickCountRef.current = Number(ex.completedPickCount) || 0;
          }
        }

        setBridgeOk(true);
      }
    } catch {
      // ignore
    } finally {
      stateInFlightRef.current = false;
    }
  }

  useEffect(() => {
    let alive = true;

    if (!effectiveBase) {
      setBridgeOk(false);
      setBridgeMsg("bridgeBase is empty (Connect에서 URL 저장 필요)");
      setPhase("Unknown");
      setLastState(null);
      return () => {};
    }

    (async () => {
      if (!alive) return;
      await refreshBridgeHealth({ silent: true });
      if (!alive) return;
      if (autoPull) await pullBridgeStateOnce();
    })();

    const healthTimer = setInterval(() => {
      if (!alive) return;
      refreshBridgeHealth({ silent: true });
    }, HEALTH_POLL_MS);

    const stateTimer = setInterval(() => {
      if (!alive) return;
      if (!autoPull) return;
      pullBridgeStateOnce();
    }, STATE_POLL_MS);

    return () => {
      alive = false;
      clearInterval(healthTimer);
      clearInterval(stateTimer);
    };
  }, [effectiveBase, effectiveToken, autoPull, manualInput, autoRecommend]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const obj = safeJsonParse(allyJsonText);
    setAllyByRole(sanitizeAlly(obj));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setAllyJsonText(JSON.stringify(allyByRole));
  }, [allyByRole]);

  async function loadMeta({ silent = false } = {}) {
    setMetaErr("");
    setMetaLoading(true);
    try {
      const j = await apiMeta(dbPath);
      const patches = Array.isArray(j?.patches) ? j.patches : [];
      const latest = String(j?.latest_patch || "");
      setAvailablePatches(patches);
      setLatestPatch(latest);

      if (patch !== "ALL" && patches.length && !patches.includes(patch)) {
        setPatch("ALL");
      }
    } catch (e) {
      if (!silent) setMetaErr(String(e?.message || e));
      setAvailablePatches([]);
      setLatestPatch("");
    } finally {
      setMetaLoading(false);
    }
  }

  useEffect(() => {
    loadMeta({ silent: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dbPath]);

  const best = useMemo(() => {
    if (!recs || !recs.length) return null;
    return recs[0];
  }, [recs]);

  return (
    <div className="grid">
      {/* LEFT */}
      <div className="card">
        <div className="h1">Recommend</div>
        <p className="p">브릿지 상태를 읽고(옵션), API(/recommend)로 추천을 호출합니다.</p>

        <div className="card" style={{ marginTop: 12 }}>
          <div className="h2">Champion Catalog</div>
          <div className="p">
            상태: <b>{catReady ? "READY" : "LOADING"}</b> — {catStatus}
          </div>
        </div>

        <div className="card" style={{ marginTop: 12 }}>
          <div className="h2">API Meta</div>

          <div className="kv">
            <div className="k">db_path</div>
            <div className="v">{dbPath}</div>

            <div className="k">latest_patch</div>
            <div className="v">{latestPatch || "(unknown)"}</div>

            <div className="k">patches</div>
            <div className="v">{availablePatches?.length ? `${availablePatches.length}개` : "(none)"}</div>
          </div>

          <div style={{ height: 10 }} />
          <div className="row">
            <button className="btn" onClick={() => loadMeta({ silent: false })} disabled={metaLoading}>
              {metaLoading ? "Loading..." : "Reload /meta"}
            </button>
            <button className="btn" onClick={() => latestPatch && setPatch(latestPatch)} disabled={!latestPatch}>
              Use latest patch
            </button>
          </div>

          {metaErr ? <div style={{ marginTop: 10, fontWeight: 900 }}>❌ meta error: {metaErr}</div> : null}
        </div>

        <div className="card" style={{ marginTop: 12 }}>
          <div className="h2">Top Recommendation</div>
          {best ? (
            <>
              <div style={{ fontWeight: 900, fontSize: 20 }}>
                {idToName?.[best.champ_id] || "UNKNOWN"} <span className="p">({best.champ_id})</span>
              </div>
              <ScoreBar value={best.final_score} />
              <div className="row" style={{ marginTop: 10 }}>
                <Metric k="final" v={best.final_score} hint="base_lb + synergy_delta + counter_delta" />
                <Metric k="base_lb" v={best.base_lb} />
                <Metric k="base_wr" v={best.base_wr} />
                <Metric k="games" v={best.games} />
                <Metric k="pick_rate(%)" v={formatPickRate(best)} />
              </div>
            </>
          ) : (
            <div className="p">(아직 추천 없음)</div>
          )}
        </div>

        <div className="card" style={{ marginTop: 12 }}>
          <div className="h2">Results</div>
          <div className="p" style={{ marginTop: 0 }}>
            last run: <b>{lastRunAt || "(none)"}</b> {apiRunning ? " — RUNNING..." : ""}
          </div>

          {apiErr ? <div style={{ marginTop: 8, fontWeight: 900 }}>❌ {apiErr}</div> : null}
          {autoRecMsg ? <div style={{ marginTop: 8, fontWeight: 900 }}>{autoRecMsg}</div> : null}

          {recs && recs.length ? (
            <div style={{ display: "grid", gap: 10, marginTop: 10 }}>
              {recs.map((r, idx) => {
                const nm = idToName?.[r.champ_id] || "UNKNOWN";
                return (
                  <div key={`rec_${r.champ_id}_${idx}`} className="card" style={{ background: "rgba(255,255,255,0.02)" }}>
                    <div className="row" style={{ justifyContent: "space-between" }}>
                      <div style={{ fontWeight: 900, fontSize: 18 }}>
                        #{idx + 1} {nm} <span className="p">({r.champ_id})</span>
                      </div>
                      <div style={{ fontWeight: 900, fontSize: 18 }}>final: {r.final_score}</div>
                    </div>
                    <ScoreBar value={r.final_score} />
                    <div className="row" style={{ marginTop: 10 }}>
                      <Metric k="base_lb" v={r.base_lb} />
                      <Metric k="base_wr" v={r.base_wr} />
                      <Metric k="games" v={r.games} />
                      <Metric k="pick_rate(%)" v={formatPickRate(r)} />
                      <Metric k="counter" v={r.counter_delta} />
                      <Metric k="c_samples" v={r.counter_samples} />
                      <Metric k="synergy" v={r.synergy_delta} />
                      <Metric k="s_samples" v={r.synergy_samples} />
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="p" style={{ marginTop: 8 }}>
              (결과가 비어있음) — 보통은 <b>패치/티어/픽률</b> 필터가 너무 빡세거나, DB에 해당 role 데이터가 부족한 경우야. Raw API를 켜서 meta를 보면 원인 힌트가 나와.
            </div>
          )}

          <div style={{ height: 10 }} />
          <label className="p" style={{ display: "flex", alignItems: "center", gap: 8, margin: 0 }}>
            <input type="checkbox" checked={showRawResults} onChange={(e) => setShowRawResults(e.target.checked)} />
            Raw API 보기
          </label>

          {showRawResults && apiRaw ? <div className="pre" style={{ marginTop: 10 }}>{JSON.stringify(apiRaw, null, 2)}</div> : null}
        </div>

        {renderHints()}
      </div>

      {/* RIGHT */}
      <div className="card">
        <div className="h2">Inputs</div>

        <div className="row">
          <button
            className="btn"
            onClick={() => {
              clearRecommendPrefs();

              setDbPath(DEFAULT_DB_PATH);
              setPatch("ALL");
              setTier("ALL");
              setMyRole("MIDDLE");

              setCandidateMode("ALL");
              setMinPickRatePct(0.5);

              setChampPoolText("103,7,61");
              setBansText("");
              setEnemyText("");

              const ally0 = emptyAlly();
              setAllyByRole(ally0);
              setAllyJsonText(JSON.stringify(ally0));

              setMinGames(1);
              setTopN(10);

              setAutoPull(true);
              setManualInput(false);
              setAutoRecommend(true);

              setShowAdvanced(false);
              setShowRawResults(false);
              setShowRawState(false);

              resetAutoRecSession();

              setApiErr("");
              setApiRaw(null);
              setRecs([]);
              setApiRunning(false);
              setLastRunAt("");
            }}
          >
            Reset prefs
          </button>

          <button className="btn" onClick={runRecommend} disabled={apiRunning} style={{ marginLeft: "auto" }}>
            {apiRunning ? "Running..." : "Run /recommend"}
          </button>
        </div>

        <div style={{ height: 10 }} />

        <div className="row">
          <div style={{ flex: 1, minWidth: 260 }}>
            <div className="p" style={{ fontWeight: 800 }}>db_path</div>
            <input className="input" value={dbPath} onChange={(e) => setDbPath(e.target.value)} />
          </div>

          <div style={{ width: 170 }}>
            <div className="p" style={{ fontWeight: 800 }}>patch</div>
            <select className="input" value={patch} onChange={(e) => setPatch(e.target.value)}>
              <option value="ALL">ALL</option>
              {availablePatches.map((p) => (
                <option key={`patch_${p}`} value={p}>{p}</option>
              ))}
            </select>
          </div>

          <div style={{ width: 170 }}>
            <div className="p" style={{ fontWeight: 800 }}>tier</div>
            <select className="input" value={tier} onChange={(e) => setTier(e.target.value)}>
              {TIERS.map((t) => (
                <option key={`tier_${t}`} value={t}>{t}</option>
              ))}
            </select>
          </div>

          <div style={{ width: 170 }}>
            <div className="p" style={{ fontWeight: 800 }}>my_role</div>
            <select className="input" value={myRole} onChange={(e) => setMyRole(e.target.value)}>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {ROLE_KO[r]} ({r})
                </option>
              ))}
            </select>
          </div>
        </div>

        <div style={{ height: 12 }} />

        <div className="card">
          <div className="h2">Candidate Mode</div>
          <div className="row" style={{ marginTop: 8 }}>
            <button
              className="btn"
              onClick={() => setCandidateMode("ALL")}
              style={{ background: candidateMode === "ALL" ? "rgba(120,140,255,0.25)" : undefined }}
            >
              전체 후보(챔프폭 무시)
            </button>
            <button
              className="btn"
              onClick={() => setCandidateMode("POOL")}
              style={{ background: candidateMode === "POOL" ? "rgba(120,140,255,0.25)" : undefined }}
            >
              내 챔프폭만
            </button>
          </div>

          <div style={{ height: 10 }} />
          <div className="p" style={{ marginTop: 0 }}>
            최소 픽률(%): <b>{Number(minPickRatePct || 0).toFixed(2)}%</b>
          </div>
          <input
            className="input"
            type="number"
            step="0.1"
            min="0"
            max="100"
            value={minPickRatePct}
            onChange={(e) => setMinPickRatePct(e.target.value)}
          />
          <div className="p" style={{ marginTop: 6, fontSize: 12, opacity: 0.9 }}>
            예) 0.5% = 해당 role/패치/티어에서 픽률 0.5% 이상만 후보로 사용
          </div>
        </div>

        <div style={{ height: 12 }} />

        {candidateMode === "POOL" ? (
          <div className="card">
            <div className="h2">Champ Pool</div>
            <div className="p">한글 이름(또는 숫자 ID)로 추가 가능. 내부는 championId로 저장/전송.</div>

            <div className="row" style={{ marginTop: 8 }}>
              <input
                className="input"
                style={{ flex: 1, minWidth: 260 }}
                value={poolName}
                onChange={(e) => setPoolName(e.target.value)}
                placeholder="예: 아리 / 애니 / 오리아나 ... 또는 103"
                onKeyDown={(e) => {
                  if (e.key !== "Enter") return;
                  e.preventDefault();

                  addByNameOrHint({
                    kind: "pool",
                    role: "",
                    input: poolName,
                    clearInput: setPoolName,
                    addByIdFallback: (cid) => addIdToText(setChampPoolText, champPoolText, cid),
                  });
                }}
              />
              <button
                className="btn"
                onClick={() => {
                  addByNameOrHint({
                    kind: "pool",
                    role: "",
                    input: poolName,
                    clearInput: setPoolName,
                    addByIdFallback: (cid) => addIdToText(setChampPoolText, champPoolText, cid),
                  });
                }}
              >
                추가
              </button>
            </div>

            {renderIdChips({
              ids: parseIds(champPoolText),
              idToName,
              onRemove: (cid) => removeIdFromText(setChampPoolText, champPoolText, cid),
            })}

            {showAdvanced ? (
              <div style={{ marginTop: 10 }}>
                <div className="p" style={{ fontWeight: 800 }}>champ_pool (IDs, comma)</div>
                <input className="input" value={champPoolText} onChange={(e) => setChampPoolText(e.target.value)} />
              </div>
            ) : null}
          </div>
        ) : (
          <div className="card">
            <div className="h2">Champ Pool</div>
            <div className="p" style={{ marginTop: 0 }}>
              현재는 <b>전체 후보 모드</b>라서 champ pool 입력이 필요 없습니다.
            </div>
          </div>
        )}

        <div style={{ height: 12 }} />

        <div className="card">
          <div className="h2">Auto Input (Bridge)</div>

          <div className="kv">
            <div className="k">bridgeBase</div>
            <div className="v">{effectiveBase || "(empty)"}</div>

            <div className="k">bridgeToken</div>
            <div className="v">{effectiveToken ? "(set)" : "(empty)"}</div>

            <div className="k">health</div>
            <div className="v">{bridgeOk ? "OK" : "FAIL"} {bridgeMsg ? `— ${bridgeMsg}` : ""}</div>

            <div className="k">phase</div>
            <div className="v">{phase}</div>

            <div className="k">input mode</div>
            <div className="v">{manualInput ? "MANUAL(수동)" : "AUTO(브릿지/확정만)"}</div>

            <div className="k">auto recommend</div>
            <div className="v">{autoRecommend ? "ON(확정 이벤트)" : "OFF"}</div>
          </div>

          <div style={{ height: 10 }} />
          <div className="row">
            <button className="btn" onClick={() => refreshBridgeHealth({ silent: false })}>Health now</button>
            <button className="btn" onClick={pullBridgeStateOnce}>Pull state once</button>

            <button
              className="btn"
              onClick={() => {
                setManualInput(false);
                setAutoPull(true);
              }}
              style={{ background: !manualInput ? "rgba(120,140,255,0.25)" : undefined }}
              title="브릿지 Pull 결과로 bans/enemy/ally가 (확정된 것만) 자동 반영됩니다."
            >
              자동 입력
            </button>

            <button
              className="btn"
              onClick={() => {
                setManualInput(true);
                setAutoPull(true);
              }}
              style={{ background: manualInput ? "rgba(120,140,255,0.25)" : undefined }}
              title="수동 입력으로 전환하면 브릿지가 입력값을 덮어쓰지 않습니다."
            >
              수동 입력
            </button>

            <label className="p" style={{ display: "flex", alignItems: "center", gap: 8, margin: 0 }}>
              <input type="checkbox" checked={autoPull} onChange={(e) => setAutoPull(e.target.checked)} />
              자동 Pull (state: 1.2s)
            </label>

            <label className="p" style={{ display: "flex", alignItems: "center", gap: 8, margin: 0 }}>
              <input
                type="checkbox"
                checked={autoRecommend}
                onChange={(e) => {
                  setAutoRecommend(e.target.checked);
                  resetAutoRecSession();
                }}
                disabled={manualInput}
                title={manualInput ? "수동 입력 모드에서는 자동추천이 동작하지 않음" : "밴/픽 확정 이벤트에서 자동으로 추천을 실행"}
              />
              자동추천(확정)
            </label>

            <label className="p" style={{ display: "flex", alignItems: "center", gap: 8, margin: 0 }}>
              <input type="checkbox" checked={showRawState} onChange={(e) => setShowRawState(e.target.checked)} />
              state raw 보기
            </label>
          </div>

          {manualInput ? (
            <div className="p" style={{ marginTop: 8, fontWeight: 900 }}>
              ✅ 수동 입력 모드: 브릿지는 phase/state만 갱신하고, 밴/픽 입력값은 덮어쓰지 않습니다.
            </div>
          ) : (
            <div className="p" style={{ marginTop: 8, fontWeight: 900 }}>
              ✅ 자동 입력 모드: 브릿지 Pull 결과가 <b>확정(completed)된 밴/픽</b>만 입력에 반영됩니다.
            </div>
          )}

          {showRawState && lastState ? <div className="pre">{JSON.stringify(lastState, null, 2)}</div> : null}
        </div>

        <div style={{ height: 12 }} />

        {/* 수동 입력 UI */}
        <div className="row">
          <div className="card" style={{ flex: 1, minWidth: 320 }}>
            <div className="h2">Bans</div>

            {manualInput ? (
              <div className="row" style={{ marginTop: 8 }}>
                <input
                  className="input"
                  style={{ flex: 1, minWidth: 240 }}
                  value={banName}
                  onChange={(e) => setBanName(e.target.value)}
                  placeholder="밴 챔프: 이름(한글) 또는 ID"
                  onKeyDown={(e) => {
                    if (e.key !== "Enter") return;
                    e.preventDefault();
                    addByNameOrHint({
                      kind: "bans",
                      role: "",
                      input: banName,
                      clearInput: setBanName,
                      addByIdFallback: (cid) => addIdToText(setBansText, bansText, cid),
                    });
                  }}
                />
                <button
                  className="btn"
                  onClick={() => {
                    addByNameOrHint({
                      kind: "bans",
                      role: "",
                      input: banName,
                      clearInput: setBanName,
                      addByIdFallback: (cid) => addIdToText(setBansText, bansText, cid),
                    });
                  }}
                >
                  추가
                </button>
              </div>
            ) : (
              <div className="p" style={{ marginTop: 6 }}>
                (자동 입력 모드) — 브릿지 Pull로 <b>확정된 밴만</b> 반영됩니다. 수동으로 넣으려면 <b>수동 입력</b>으로 전환하세요.
              </div>
            )}

            {renderIdChips({
              ids: parseIds(bansText),
              idToName,
              onRemove: (cid) => removeIdFromText(setBansText, bansText, cid),
            })}

            {showAdvanced ? (
              <div style={{ marginTop: 10 }}>
                <div className="p" style={{ fontWeight: 800 }}>bans (IDs)</div>
                <input className="input" value={bansText} onChange={(e) => setBansText(e.target.value)} />
              </div>
            ) : null}
          </div>

          <div className="card" style={{ flex: 1, minWidth: 320 }}>
            <div className="h2">Enemy</div>

            {manualInput ? (
              <div className="row" style={{ marginTop: 8 }}>
                <input
                  className="input"
                  style={{ flex: 1, minWidth: 240 }}
                  value={enemyName}
                  onChange={(e) => setEnemyName(e.target.value)}
                  placeholder="적 챔프: 이름(한글) 또는 ID"
                  onKeyDown={(e) => {
                    if (e.key !== "Enter") return;
                    e.preventDefault();
                    addByNameOrHint({
                      kind: "enemy",
                      role: "",
                      input: enemyName,
                      clearInput: setEnemyName,
                      addByIdFallback: (cid) => addIdToText(setEnemyText, enemyText, cid),
                    });
                  }}
                />
                <button
                  className="btn"
                  onClick={() => {
                    addByNameOrHint({
                      kind: "enemy",
                      role: "",
                      input: enemyName,
                      clearInput: setEnemyName,
                      addByIdFallback: (cid) => addIdToText(setEnemyText, enemyText, cid),
                    });
                  }}
                >
                  추가
                </button>
              </div>
            ) : (
              <div className="p" style={{ marginTop: 6 }}>
                (자동 입력 모드) — 브릿지 Pull로 <b>확정된 픽만</b> 반영됩니다. 수동으로 넣으려면 <b>수동 입력</b>으로 전환하세요.
              </div>
            )}

            {renderIdChips({
              ids: parseIds(enemyText),
              idToName,
              onRemove: (cid) => removeIdFromText(setEnemyText, enemyText, cid),
            })}

            {showAdvanced ? (
              <div style={{ marginTop: 10 }}>
                <div className="p" style={{ fontWeight: 800 }}>enemy_picks (IDs)</div>
                <input className="input" value={enemyText} onChange={(e) => setEnemyText(e.target.value)} />
              </div>
            ) : null}
          </div>
        </div>

        <div style={{ height: 12 }} />

        <div className="card">
          <div className="h2">Ally Picks (by role)</div>
          <div className="p">자동 모드에선 브릿지 Pull로 확정된 픽만 반영. 수동 모드에선 아래 입력으로 추가/제거.</div>

          <div style={{ marginTop: 10 }}>
            {ROLES.map((r) => (
              <div key={`ally_${r}`} className="card" style={{ marginTop: 10 }}>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <div className="h2" style={{ margin: 0 }}>
                    {ROLE_KO[r]} ({r})
                  </div>
                  <div className="row">
                    <button
                      className="btn"
                      onClick={() => {
                        setAllyByRole((prev) => {
                          const next = { ...prev };
                          next[r] = [];
                          return next;
                        });
                      }}
                    >
                      Clear
                    </button>
                  </div>
                </div>

                {manualInput ? (
                  <div className="row" style={{ marginTop: 8 }}>
                    <input
                      className="input"
                      style={{ flex: 1, minWidth: 240 }}
                      value={allyNameByRole?.[r] || ""}
                      onChange={(e) => setAllyNameByRole((prev) => ({ ...prev, [r]: e.target.value }))}
                      placeholder="아군 챔프: 이름(한글) 또는 ID"
                      onKeyDown={(e) => {
                        if (e.key !== "Enter") return;
                        e.preventDefault();

                        const input = allyNameByRole?.[r] || "";
                        addByNameOrHint({
                          kind: "ally",
                          role: r,
                          input,
                          clearInput: (v) => setAllyNameByRole((prev) => ({ ...prev, [r]: v })),
                          addByIdFallback: (cid) =>
                            setAllyByRole((prev) => {
                              const next = { ...prev };
                              const arr = Array.isArray(next[r]) ? [...next[r]] : [];
                              if (!arr.includes(cid)) arr.push(cid);
                              next[r] = arr;
                              return next;
                            }),
                        });
                      }}
                    />
                    <button
                      className="btn"
                      onClick={() => {
                        const input = allyNameByRole?.[r] || "";
                        addByNameOrHint({
                          kind: "ally",
                          role: r,
                          input,
                          clearInput: (v) => setAllyNameByRole((prev) => ({ ...prev, [r]: v })),
                          addByIdFallback: (cid) =>
                            setAllyByRole((prev) => {
                              const next = { ...prev };
                              const arr = Array.isArray(next[r]) ? [...next[r]] : [];
                              if (!arr.includes(cid)) arr.push(cid);
                              next[r] = arr;
                              return next;
                            }),
                        });
                      }}
                    >
                      추가
                    </button>
                  </div>
                ) : (
                  <div className="p" style={{ marginTop: 6 }}>
                    (자동 입력 모드) — <b>확정된 픽만</b> 자동 반영됩니다. 수동 입력 UI는 <b>수동 입력</b>으로 전환하면 나타납니다.
                  </div>
                )}

                {renderIdChips({
                  ids: allyByRole?.[r] || [],
                  idToName,
                  onRemove: (cid) => {
                    setAllyByRole((prev) => {
                      const next = { ...prev };
                      next[r] = (next[r] || []).filter((x) => x !== cid);
                      return next;
                    });
                  },
                })}
              </div>
            ))}
          </div>

          {showAdvanced ? (
            <div style={{ marginTop: 10 }}>
              <div className="p" style={{ fontWeight: 800 }}>ally_picks_by_role (JSON)</div>
              <textarea
                className="textarea"
                value={allyJsonText}
                onChange={(e) => {
                  const txt = e.target.value;
                  setAllyJsonText(txt);
                  setAllyByRole(sanitizeAlly(safeJsonParse(txt)));
                }}
              />
            </div>
          ) : null}
        </div>

        <div style={{ height: 12 }} />

        <div className="card">
          <div className="h2">Options</div>

          <div className="row">
            <div style={{ width: 180 }}>
              <div className="p" style={{ fontWeight: 800 }}>min_games</div>
              <input className="input" type="number" min="1" value={minGames} onChange={(e) => setMinGames(e.target.value)} />
              <div className="p" style={{ marginTop: 6, fontSize: 12, opacity: 0.9 }}>
                백엔드 검증 때문에 1 이상만 전송됩니다.
              </div>
            </div>
            <div style={{ width: 180 }}>
              <div className="p" style={{ fontWeight: 800 }}>top_n</div>
              <input className="input" type="number" min="1" value={topN} onChange={(e) => setTopN(e.target.value)} />
            </div>

            <label className="p" style={{ display: "flex", alignItems: "center", gap: 8, margin: 0 }}>
              <input type="checkbox" checked={showAdvanced} onChange={(e) => setShowAdvanced(e.target.checked)} />
              고급 입력(ID/JSON) 보기
            </label>
          </div>
        </div>
      </div>
    </div>
  );
}
