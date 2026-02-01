// web/lib/bridge.js
// - Bridge /health, /state 호출 유틸
// - 폴링 환경에서 "JSON 파싱 실패"가 UI를 흔드는 걸 막기 위해 안전 파서 사용
// - 401/HTTP 에러/네트워크 에러를 항상 사람이 읽는 msg로 정리

function safeJsonParse(txt) {
  if (!txt) return null;
  try {
    return JSON.parse(txt);
  } catch {
    return { _raw: txt };
  }
}

function baseUrl(x) {
  return String(x || "").trim().replace(/\/$/, "");
}

function mkHeaders(bridgeToken) {
  const headers = {};
  if (bridgeToken) headers["X-LOPA-TOKEN"] = String(bridgeToken).trim();
  return headers;
}

async function fetchBridge(path, { bridgeBase, bridgeToken, timeoutMs = 2000 }) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);

  const url = `${baseUrl(bridgeBase)}/${String(path || "").replace(/^\//, "")}`;

  try {
    const r = await fetch(url, {
      method: "GET",
      headers: mkHeaders(bridgeToken),
      signal: controller.signal,
      cache: "no-store",
    });

    const txt = await r.text();
    const j = safeJsonParse(txt) || {};

    // 표준화된 리턴
    if (r.status === 401) {
      return { ok: false, msg: "401 invalid token", status: 401, raw: j, url };
    }
    if (!r.ok) {
      return { ok: false, msg: `HTTP ${r.status}`, status: r.status, raw: j, url };
    }

    // 정상
    // 브릿지 응답이 보통 {ok:true, ...} 형태라 그대로 반환
    return j && typeof j === "object" ? { ...j, url } : { ok: true, data: j, url };
  } catch (e) {
    const isAbort = e?.name === "AbortError";
    const msg = isAbort ? `timeout (${timeoutMs}ms)` : String(e?.message || e);
    return { ok: false, msg, error: msg, status: 0, url };
  } finally {
    clearTimeout(id);
  }
}

export async function bridgeHealth({ bridgeBase, bridgeToken, timeoutMs = 2000 }) {
  return await fetchBridge("/health", { bridgeBase, bridgeToken, timeoutMs });
}

export async function bridgeState({ bridgeBase, bridgeToken, timeoutMs = 2000 }) {
  return await fetchBridge("/state", { bridgeBase, bridgeToken, timeoutMs });
}
