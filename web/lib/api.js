// web/lib/api.js

const DEFAULT_API =
  (typeof process !== "undefined" && process.env && process.env.NEXT_PUBLIC_API_BASE) ||
  "http://127.0.0.1:8000";

async function fetchJsonOrText(url, opts = {}) {
  const r = await fetch(url, opts);
  const txt = await r.text();

  let j = null;
  try {
    j = txt ? JSON.parse(txt) : null;
  } catch {
    j = null;
  }

  if (!r.ok) {
    // FastAPI는 detail이 string / object / array 모두 가능
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
        ? JSON.stringify(detail, null, 2)
        : `HTTP ${r.status}`;

    const err = new Error(msg);
    err.status = r.status;
    err.url = url;
    err.body = j ?? { _raw: txt };
    throw err;
  }

  // 정상 응답
  return j ?? { _raw: txt };
}

export async function apiHealth(apiBase = DEFAULT_API) {
  const base = String(apiBase || "").replace(/\/$/, "");
  return await fetchJsonOrText(`${base}/health`, { method: "GET" });
}

export async function apiRecommend(body, apiBase = DEFAULT_API) {
  const base = String(apiBase || "").replace(/\/$/, "");
  return await fetchJsonOrText(`${base}/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function apiMeta(dbPath, apiBase = DEFAULT_API) {
  const base = String(apiBase || "").replace(/\/$/, "");
  const qs = new URLSearchParams();
  if (dbPath) qs.set("db_path", String(dbPath));
  return await fetchJsonOrText(`${base}/meta?${qs.toString()}`, { method: "GET" });
}
