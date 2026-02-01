// web/lib/api.js

const DEFAULT_API =
  (typeof process !== "undefined" && process.env && process.env.NEXT_PUBLIC_API_BASE) ||
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
    const msg = j?.detail ? String(j.detail) : `HTTP ${r.status}`;
    throw new Error(msg);
  }

  return j;
}

export async function apiHealth(apiBase = DEFAULT_API) {
  const base = String(apiBase || "").replace(/\/$/, "");
  return await fetchText(`${base}/health`, { method: "GET" });
}

export async function apiRecommend(body, apiBase = DEFAULT_API) {
  const base = String(apiBase || "").replace(/\/$/, "");
  return await fetchText(`${base}/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function apiMeta(dbPath, apiBase = DEFAULT_API) {
  const base = String(apiBase || "").replace(/\/$/, "");
  const qs = new URLSearchParams();
  if (dbPath) qs.set("db_path", String(dbPath));
  return await fetchText(`${base}/meta?${qs.toString()}`, { method: "GET" });
}
