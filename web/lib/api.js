// web/lib/api.js

const DEFAULT_API =
  (typeof process !== "undefined" &&
    process.env &&
    (process.env.NEXT_PUBLIC_LOPA_API_BASE || process.env.NEXT_PUBLIC_API_BASE)) ||
  "http://127.0.0.1:8000";

async function fetchText(url, opts = {}) {
  const r = await fetch(url, opts);
  const txt = await r.text();

  let j = null;
  try {
    j = txt ? JSON.parse(txt) : null;
  } catch {
    j = { _raw: txt };
  }

  if (!r.ok) {
    // FastAPI는 보통 {"detail": "..."} 형태
    const msg =
      j && typeof j === "object"
        ? (j.detail ? String(j.detail) : j.msg ? String(j.msg) : `HTTP ${r.status}`)
        : `HTTP ${r.status}`;

    // ❗️예전처럼 [object Object] 뜨는 걸 방지: 최대한 문자열로 만든다
    throw new Error(msg);
  }

  return j;
}

export async function apiRecommend(body, apiBase = DEFAULT_API) {
  const base = String(apiBase || DEFAULT_API).replace(/\/$/, "");
  return await fetchText(`${base}/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// /meta (patch list, latest_patch)
export async function apiMeta(dbPath, apiBase = DEFAULT_API) {
  const base = String(apiBase || DEFAULT_API).replace(/\/$/, "");
  const qs = new URLSearchParams();
  if (dbPath) qs.set("db_path", String(dbPath));
  return await fetchText(`${base}/meta?${qs.toString()}`, { method: "GET" });
}
