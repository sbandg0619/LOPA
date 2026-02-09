// web/lib/api.js
// - 배포에서 localhost API(127.0.0.1:8000)로 떨어지는 걸 자동 방지
// - 우선순위: (1) 인자 > (2) localStorage(apiBase) > (3) env(NEXT_PUBLIC_API_BASE) > (4) host 기준 기본값

export const API_BASE =
  (typeof process !== "undefined" && process.env && process.env.NEXT_PUBLIC_API_BASE) || "";

const DEFAULT_TIMEOUT_MS = 15000;

function isBrowser() {
  return typeof window !== "undefined";
}

function isLocalhostHostname(host) {
  const h = String(host || "").trim().toLowerCase();
  return h === "localhost" || h === "127.0.0.1";
}

function isLocalApiBase(base) {
  const b = String(base || "").trim().toLowerCase();
  return b.startsWith("http://127.0.0.1") || b.startsWith("http://localhost");
}

function defaultApiBaseByHost() {
  // env가 없을 때 최종 fallback
  try {
    if (isBrowser()) {
      const onLocal = isLocalhostHostname(window.location.hostname || "");
      return onLocal ? "http://127.0.0.1:8000" : "https://lopa-api.onrender.com";
    }
  } catch {}
  return "http://127.0.0.1:8000";
}

// ✅ 런타임(브라우저)에서 저장된 apiBase가 있으면 우선 사용
// - 단, "배포 환경"에서는 local api(127/localhost)면 자동 무시
function getRuntimeApiBase() {
  try {
    if (!isBrowser()) return "";

    // eslint-disable-next-line global-require
    const { getApiBase } = require("./constants");
    if (typeof getApiBase !== "function") return "";

    const raw = String(getApiBase() || "").trim();
    if (!raw) return "";

    if (!(raw.startsWith("http://") || raw.startsWith("https://"))) return "";

    const cleaned = raw.replace(/\/$/, "");

    const host = String(window.location.hostname || "");
    const onLocalhost = isLocalhostHostname(host);
    if (!onLocalhost && isLocalApiBase(cleaned)) return "";

    return cleaned;
  } catch {
    return "";
  }
}

function resolveApiBase(apiBaseArg) {
  const arg = String(apiBaseArg || "").trim().replace(/\/$/, "");
  if (arg) return arg;

  const rt = getRuntimeApiBase();
  if (rt) return rt;

  const env = String(API_BASE || "").trim().replace(/\/$/, "");
  if (env) return env;

  return defaultApiBaseByHost();
}

function toPrettyString(x, fallback = "") {
  try {
    if (typeof x === "string") return x;
    if (x === null || typeof x === "undefined") return fallback;
    return JSON.stringify(x, null, 2);
  } catch {
    try {
      return String(x);
    } catch {
      return fallback;
    }
  }
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function fetchJsonOrText(url, opts = {}) {
  const timeoutMs = Number(opts.timeoutMs ?? DEFAULT_TIMEOUT_MS) || DEFAULT_TIMEOUT_MS;
  const { timeoutMs: _timeoutMs, ...fetchOpts } = opts;

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);

  try {
    const r = await fetch(url, { ...fetchOpts, signal: ctrl.signal });
    const txt = await r.text();

    let j = null;
    try {
      j = txt ? JSON.parse(txt) : null;
    } catch {
      j = null;
    }

    if (!r.ok) {
      let detail = null;
      if (j && typeof j === "object") detail = j.detail ?? j;
      else detail = txt;

      const msg =
        typeof detail === "string"
          ? detail
          : detail
          ? toPrettyString(detail, `HTTP ${r.status}`)
          : `HTTP ${r.status}`;

      const err = new Error(msg);
      err.status = r.status;
      err.url = url;
      err.body = j ?? { _raw: txt };
      err.rawText = txt;
      throw err;
    }

    return j ?? { _raw: txt };
  } catch (e) {
    const isAbort = e?.name === "AbortError";
    const baseMsg = isAbort ? `Request timeout (${timeoutMs}ms)` : (e?.message ? String(e.message) : String(e));
    const err = new Error(`${baseMsg} — ${url}`);
    err.url = url;
    err.cause = e;
    err.status = e?.status;
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

// 콜드스타트/슬립 깨우기용 재시도 (GET /meta 같은 가벼운 요청)
async function fetchWithRetry(url, opts = {}, { retries = 2, backoffMs = 800 } = {}) {
  let lastErr = null;
  for (let i = 0; i <= retries; i++) {
    try {
      return await fetchJsonOrText(url, opts);
    } catch (e) {
      lastErr = e;
      const status = Number(e?.status);
      const msg = String(e?.message || "");
      const retryable =
        msg.includes("Request timeout") ||
        msg.includes("Failed to fetch") ||
        (Number.isFinite(status) && status >= 500);

      if (!retryable || i === retries) break;
      await sleep(backoffMs * (i + 1));
    }
  }
  throw lastErr;
}

export async function apiHealth(apiBase) {
  const base = resolveApiBase(apiBase);
  return await fetchJsonOrText(`${base}/health`, { method: "GET" });
}

export async function apiRecommend(body, apiBase) {
  const base = resolveApiBase(apiBase);
  return await fetchJsonOrText(`${base}/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function apiMeta(dbPath, apiBase) {
  const base = resolveApiBase(apiBase);
  const qs = new URLSearchParams();
  if (dbPath) qs.set("db_path", String(dbPath));
  return await fetchWithRetry(`${base}/meta?${qs.toString()}`, { method: "GET" }, { retries: 2, backoffMs: 800 });
}

export function getEffectiveApiBase(apiBaseArg) {
  return resolveApiBase(apiBaseArg);
}
