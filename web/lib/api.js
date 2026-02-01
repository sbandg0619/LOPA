// web/lib/api.js

export const API_BASE =
  (typeof process !== "undefined" && process.env && process.env.NEXT_PUBLIC_API_BASE) ||
  "http://127.0.0.1:8000";

const DEFAULT_TIMEOUT_MS = 15000;

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
      // FastAPI detail은 string/object/array 모두 가능
      let detail = null;
      if (j && typeof j === "object") {
        detail = j.detail ?? j;
      } else {
        detail = txt;
      }

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
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export async function apiHealth(apiBase = API_BASE) {
  const base = String(apiBase || "").replace(/\/$/, "");
  return await fetchJsonOrText(`${base}/health`, { method: "GET" });
}

export async function apiRecommend(body, apiBase = API_BASE) {
  const base = String(apiBase || "").replace(/\/$/, "");
  return await fetchJsonOrText(`${base}/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function apiMeta(dbPath, apiBase = API_BASE) {
  const base = String(apiBase || "").replace(/\/$/, "");
  const qs = new URLSearchParams();
  if (dbPath) qs.set("db_path", String(dbPath));
  return await fetchJsonOrText(`${base}/meta?${qs.toString()}`, { method: "GET" });
}
