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
 * pick_rate 표시 유틸
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

  if (nameToId && nameToId[q]) return { id: parseInt(nameToId[q], 10), candidates: [] };

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

function isLocalHost() {
  if (typeof window === "undefined") return false;
  const h = String(window.location?.hostname || "");
  return h === "localhost" || h === "127.0.0.1";
}

export default function RecommendPage() {
  const [bridgeBase, setBridgeBase] = useState("");
  const [bridgeToken, setBridgeToken] = useState("");

  const [bridgeOk, setBridgeOk] = useState(false);
  const [bridgeMsg, setBridgeMsg] = useState("");
  const [phase, setPhase] = useState("Unknown");
  const [lastState, setLastState] = useState(null);

  const [autoPull, setAutoPull] = useState(true);

  const LOCAL = typeof window !== "undefined" ? isLocalHost() : false;

  const DEFAULT_DB_PATH = LOCAL ? "lol_graph_personal.db" : "lol_graph_public.db";

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

  const [champPoolText, setChampPoolText] = useState("");
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

  useEffect(() => {
    if (prefsLoadedRef.current) return;
    prefsLoadedRef.current = true;

    const p = loadRecommendPrefs();
    if (!p) return;

    // 배포 환경에서는 public로 강제(개인 db_path가 섞여 meta/recommend 깨지는 것 방지)
    if (LOCAL) {
      if (p.dbPath) setDbPath(p.dbPath);
    } else {
      setDbPath("lol_graph_public.db");
    }

    if (p.patch) setPatch(p.patch);
    if (p.tier) setTier(p.tier);
    if (p.myRole) setMyRole(p.myRole);

    if (typeof p.champPoolText === "string") setChampPoolText(p.champPoolText);
    if (typeof p.bansText === "string") setBansText(p.bansText);
    if (typeof p.enemyText === "string") setEnemyText(p.enemyText);

    const ally2 = sanitizeAlly(p.allyByRole || emptyAlly());
    setAllyByRole(ally2);
    setAllyJsonText(JSON.stringify(ally2));

    // min_games는 항상 1 이상
    const mg = Math.max(1, Number(p.minGames) || 1);
    setMinGames(mg);

    setTopN(Math.max(1, Number(p.topN) || 10));

    setAutoPull(Boolean(p.autoPull));
    setShowAdvanced(Boolean(p.showAdvanced));
    setShowRawResults(Boolean(p.showRawResults));
    setShowRawState(Boolean(p.showRawState));

    if (p.candidateMode) setCandidateMode(String(p.candidateMode));

    // 0도 유효한 값이므로 || 로 처리하지 않음
    if (typeof p.minPickRatePct !== "undefined") {
      const n = Number(p.minPickRatePct);
      setMinPickRatePct(Number.isFinite(n) ? n : 0.5);
    }
  }, [LOCAL]);

  const saveTimerRef = useRef(null);
  useEffect(() => {
    if (!prefsLoadedRef.current) return;

    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      saveRecommendPrefs({
        dbPath: LOCAL ? dbPath : "lol_graph_public.db",
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
        showAdvanced,
        showRawResults,
        showRawState,
      });
    }, 400);

    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, [
    LOCAL,
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
        setPhase(j.state.phase || "Unknown");

        const bans = extractBans(j.state);
        const enemy = extractEnemy(j.state);
        const ally = extractAllyByRole(j.state);

        setBansText(idsToText(bans));
        setEnemyText(idsToText(enemy));

        const ally2 = sanitizeAlly(ally);
        setAllyByRole(ally2);
        setAllyJsonText(JSON.stringify(ally2));

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
  }, [effectiveBase, effectiveToken, autoPull]); // eslint-disable-line react-hooks/exhaustive-deps

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
      const j = await apiMeta(LOCAL ? dbPath : "lol_graph_public.db");
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
  }, [dbPath, LOCAL]);

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

  const [poolName, setPoolName] = useState("");
  const [nameHints, setNameHints] = useState({ kind: "", cands: [] });

  function applyHintPick(kind, cid) {
    setNameHints({ kind: "", cands: [] });
    if (kind === "pool") addIdToText(setChampPoolText, champPoolText, cid);
  }

  function renderHints() {
    if (!nameHints?.cands?.length) return null;
    return (
      <div className="card" style={{ marginTop: 10 }}>
        <div className="h2">이름 후보</div>
        <div className="p">정확히 매칭이 안돼서 후보를 띄웠음. 하나 클릭하면 추가됨.</div>
        <div style={{ marginTop: 8 }} className="row">
          {nameHints.cands.map((cid) => (
            <button key={`hint_btn_${cid}`} className="btn" onClick={() => applyHintPick(nameHints.kind, cid)}>
              {idToName?.[cid] || `UNKNOWN (${cid})`}
            </button>
          ))}
          <button className="btn" onClick={() => setNameHints({ kind: "", cands: [] })}>
            닫기
          </button>
        </div>
      </div>
    );
  }

  async function runRecommend() {
    setApiRunning(true);
    setLastRunAt(new Date().toLocaleTimeString());
    setApiErr("");
    setApiRaw(null);
    setRecs([]);

    if (candidateMode === "POOL" && !champPoolIds.length) {
      setApiErr("POOL 모드인데 champ_pool이 비어있음 (내 챔프폭을 최소 1개 추가해야 함)");
      setApiRunning(false);
      return;
    }

    const minPickRate = Math.max(0, Number(minPickRatePct) || 0) / 100.0;

    // ✅ 핵심: ALL 모드면 champ_pool 키 자체를 보내지 않음(omit)
    const body = {
      db_path: LOCAL ? dbPath : "lol_graph_public.db",
      patch,
      tier,
      my_role: myRole,

      use_champ_pool: candidateMode === "POOL",

      ...(candidateMode === "POOL" ? { champ_pool: champPoolIds } : {}),

      bans: bansIds,
      enemy_picks: enemyIds,
      ally_picks_by_role: allyByRole,

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
    } finally {
      setApiRunning(false);
    }
  }

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
            <div className="v">{LOCAL ? dbPath : "lol_graph_public.db"}</div>

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

              setChampPoolText("");
              setBansText("");
              setEnemyText("");

              const ally0 = emptyAlly();
              setAllyByRole(ally0);
              setAllyJsonText(JSON.stringify(ally0));

              setMinGames(1);
              setTopN(10);

              setAutoPull(true);
              setShowAdvanced(false);
              setShowRawResults(false);
              setShowRawState(false);

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
            <input
              className="input"
              value={LOCAL ? dbPath : "lol_graph_public.db"}
              disabled={!LOCAL}
              onChange={(e) => setDbPath(e.target.value)}
            />
            {!LOCAL ? (
              <div className="p" style={{ marginTop: 6, fontSize: 12, opacity: 0.9 }}>
                배포 환경에서는 public DB만 사용합니다.
              </div>
            ) : null}
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
            <div className="p">한글 이름으로 추가 가능. 내부는 championId로 저장/전송.</div>

            <div className="row" style={{ marginTop: 8 }}>
              <input
                className="input"
                style={{ flex: 1, minWidth: 260 }}
                value={poolName}
                onChange={(e) => setPoolName(e.target.value)}
                placeholder="예: 아리 / 애니 / 오리아나 ..."
                onKeyDown={(e) => {
                  if (e.key !== "Enter") return;
                  e.preventDefault();
                  const { id, candidates } = resolveChampionIdByName(poolName, { nameToId, normToId });
                  if (id) {
                    addIdToText(setChampPoolText, champPoolText, id);
                    setPoolName("");
                  } else if (candidates?.length) {
                    setNameHints({ kind: "pool", cands: candidates });
                  }
                }}
              />
              <button
                className="btn"
                onClick={() => {
                  const { id, candidates } = resolveChampionIdByName(poolName, { nameToId, normToId });
                  if (id) {
                    addIdToText(setChampPoolText, champPoolText, id);
                    setPoolName("");
                  } else if (candidates?.length) {
                    setNameHints({ kind: "pool", cands: candidates });
                  }
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
          </div>

          <div style={{ height: 10 }} />
          <div className="row">
            <button className="btn" onClick={() => refreshBridgeHealth({ silent: false })}>Health now</button>
            <button className="btn" onClick={pullBridgeStateOnce}>Pull state once</button>
            <label className="p" style={{ display: "flex", alignItems: "center", gap: 8, margin: 0 }}>
              <input type="checkbox" checked={autoPull} onChange={(e) => setAutoPull(e.target.checked)} />
              자동 Pull (state: 1.2s)
            </label>
            <label className="p" style={{ display: "flex", alignItems: "center", gap: 8, margin: 0 }}>
              <input type="checkbox" checked={showRawState} onChange={(e) => setShowRawState(e.target.checked)} />
              state raw 보기
            </label>
          </div>

          {showRawState && lastState ? <div className="pre">{JSON.stringify(lastState, null, 2)}</div> : null}
        </div>

        <div style={{ height: 12 }} />

        <div className="row">
          <div className="card" style={{ flex: 1, minWidth: 320 }}>
            <div className="h2">Bans</div>
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
          <div className="p">브릿지 Pull로 들어오면 자동 반영되며, 그대로 저장됩니다.</div>

          <div style={{ marginTop: 10 }}>
            {ROLES.map((r) => (
              <div key={`ally_${r}`} className="card" style={{ marginTop: 10 }}>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <div className="h2" style={{ margin: 0 }}>
                    {ROLE_KO[r]} ({r})
                  </div>
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
              <input
                className="input"
                type="number"
                min="1"
                value={minGames}
                onChange={(e) => setMinGames(e.target.value)}
              />
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

function extractBans(state) {
  const bans = [];
  const b = state?.bans || {};
  const my = b.myTeamBans || [];
  const th = b.theirTeamBans || [];
  for (const x of [...my, ...th]) {
    const n = parseInt(x, 10);
    if (Number.isFinite(n) && n !== 0 && !bans.includes(n)) bans.push(n);
  }
  return bans;
}

function extractEnemy(state) {
  const out = [];
  for (const p of state?.theirTeam || []) {
    const n = parseInt(p?.championId || 0, 10);
    if (Number.isFinite(n) && n !== 0 && !out.includes(n)) out.push(n);
  }
  return out;
}

function extractAllyByRole(state) {
  const map = { TOP: [], JUNGLE: [], MIDDLE: [], BOTTOM: [], UTILITY: [] };
  const posToRole = {
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

  for (const p of state?.myTeam || []) {
    const cid = parseInt(p?.championId || 0, 10);
    if (!Number.isFinite(cid) || cid === 0) continue;
    const pos = String(p?.assignedPosition || "").toLowerCase();
    const role = posToRole[pos];
    if (role && !map[role].includes(cid)) map[role].push(cid);
  }
  return map;
}
