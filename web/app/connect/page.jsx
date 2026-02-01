"use client";

// web/app/connect/page.jsx
// 목적:
// 1) 여기서 저장한 토큰/URL이 Recommend에서 동일하게 읽히게 함.
// 2) /connect?bridge=...&token=...&next=/recommend 로 들어오면
//    자동으로 저장 후 next로 이동(=자동이동 복구)

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { bridgeHealth, bridgeState } from "../../lib/bridge";
import { getBridgeBase, getBridgeToken, setBridgeConfig, clearBridgeConfig } from "../../lib/constants";

function ConnectInner() {
  const router = useRouter();
  const sp = useSearchParams();

  const [bridgeBase, setBridgeBase] = useState("");
  const [bridgeToken, setBridgeToken] = useState("");
  const [msg, setMsg] = useState("");
  const [raw, setRaw] = useState(null);

  // URL params (있으면 자동 저장+이동)
  const qsBridge = useMemo(() => (sp.get("bridge") || "").trim(), [sp]);
  const qsToken = useMemo(() => (sp.get("token") || "").trim(), [sp]);
  const qsNext = useMemo(() => (sp.get("next") || "/recommend").trim() || "/recommend", [sp]);

  // 1) 최초: localStorage 값 로드
  useEffect(() => {
    setBridgeBase(getBridgeBase());
    setBridgeToken(getBridgeToken());
  }, []);

  // 2) URL 파라미터가 있으면 입력칸에도 반영 (보이는 값)
  useEffect(() => {
    if (qsBridge) setBridgeBase(qsBridge);
    if (qsToken) setBridgeToken(qsToken);
  }, [qsBridge, qsToken]);

  const effectiveBase = useMemo(() => (bridgeBase || "").trim().replace(/\/$/, ""), [bridgeBase]);
  const effectiveToken = useMemo(() => (bridgeToken || "").trim(), [bridgeToken]);

  // 3) URL 파라미터가 있으면 자동 저장 + 자동 이동
  useEffect(() => {
    if (!qsBridge && !qsToken) return;

    // 저장
    setBridgeConfig({ bridgeBase: qsBridge || effectiveBase, bridgeToken: qsToken || effectiveToken });

    // 토큰이 주소창에 남지 않게 query 없는 URL로 바꿔치기 후 이동
    router.replace(qsNext);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qsBridge, qsToken, qsNext]);

  async function onTestHealth() {
    setMsg("Testing /health ...");
    setRaw(null);
    try {
      const j = await bridgeHealth({ bridgeBase: effectiveBase, bridgeToken: effectiveToken, timeoutMs: 2000 });
      setRaw(j);
      if (j && j.ok) setMsg("✅ Bridge OK (health)");
      else setMsg(`❌ Bridge FAIL (health): ${j?.msg || "unknown"}`);
    } catch (e) {
      setMsg(`❌ Bridge error: ${String(e)}`);
    }
  }

  async function onTestState() {
    setMsg("Testing /state ...");
    setRaw(null);
    try {
      const j = await bridgeState({ bridgeBase: effectiveBase, bridgeToken: effectiveToken, timeoutMs: 2000 });
      setRaw(j);
      if (j && j.ok) setMsg("✅ Bridge OK (state)");
      else setMsg(`❌ Bridge FAIL (state): ${j?.msg || "unknown"}`);
    } catch (e) {
      setMsg(`❌ Bridge error: ${String(e)}`);
    }
  }

  function onSaveOnly() {
    setBridgeConfig({ bridgeBase: effectiveBase, bridgeToken: effectiveToken });
    setMsg("✅ Saved to localStorage. 이제 Recommend에서 401 없이 붙어야 함.");
    setRaw(null);
  }

  function onSaveAndGo() {
    setBridgeConfig({ bridgeBase: effectiveBase, bridgeToken: effectiveToken });
    router.push("/recommend");
  }

  function onClear() {
    clearBridgeConfig();
    setBridgeBase("http://127.0.0.1:12145");
    setBridgeToken("");
    setMsg("🧹 Cleared local config.");
    setRaw(null);
  }

  return (
    <div className="card">
      <div className="h1">Connect</div>
      <p className="p">
        브릿지는 <b style={{ color: "var(--text)" }}>사용자 PC</b>에서 LCU를 읽고, 웹은{" "}
        <b style={{ color: "var(--text)" }}>localhost 브릿지</b>에서 상태만 읽습니다.
        <br />
        <span style={{ opacity: 0.9 }}>
          TIP: <b style={{ color: "var(--text)" }}>/connect?bridge=...&token=...&next=/recommend</b> 로 들어오면 자동 저장 후 자동 이동합니다.
        </span>
      </p>

      <div style={{ height: 10 }} />

      <div className="card">
        <div className="grid" style={{ gridTemplateColumns: "1fr", gap: 12 }}>
          <label>
            <div className="p" style={{ fontWeight: 900, marginBottom: 6 }}>
              Bridge URL
            </div>
            <input
              className="input"
              value={bridgeBase}
              onChange={(e) => setBridgeBase(e.target.value)}
              placeholder="http://127.0.0.1:12145"
            />
          </label>

          <label>
            <div className="p" style={{ fontWeight: 900, marginBottom: 6 }}>
              Bridge Token
            </div>
            <input
              className="input"
              value={bridgeToken}
              onChange={(e) => setBridgeToken(e.target.value)}
              placeholder="브릿지 콘솔에 출력된 token"
            />
          </label>

          <div className="row" style={{ marginTop: 4 }}>
            <button className="btn" onClick={onSaveOnly}>
              Save (local)
            </button>
            <button className="btn" onClick={onSaveAndGo}>
              Save + Go Recommend
            </button>
            <button className="btn" onClick={onTestHealth}>
              Test /health
            </button>
            <button className="btn" onClick={onTestState}>
              Test /state
            </button>
            <button className="btn" onClick={onClear} style={{ background: "rgba(255,255,255,0.03)" }}>
              Clear
            </button>
          </div>

          {msg ? <div style={{ marginTop: 6, fontWeight: 900 }}>{msg}</div> : null}

          <div style={{ marginTop: 8 }}>
            <div className="p" style={{ margin: 0 }}>
              현재 적용 값(입력칸 기준):
            </div>
            <div className="pre">
              {`bridgeBase: ${effectiveBase || "(empty)"}\nbridgeToken: ${effectiveToken ? "(set)" : "(empty)"}`}
            </div>
          </div>

          {raw ? (
            <div style={{ marginTop: 8 }}>
              <div className="p" style={{ fontWeight: 900, margin: 0 }}>
                Raw response
              </div>
              <div className="pre">{JSON.stringify(raw, null, 2)}</div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export default function ConnectPage() {
  return (
    <Suspense fallback={<div className="card"><div className="p">loading...</div></div>}>
      <ConnectInner />
    </Suspense>
  );
}
