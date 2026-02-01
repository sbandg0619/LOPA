"use client";

// web/app/autoconnect/page.jsx
// 목적: URL 파라미터(bridge/token)를 받으면 localStorage에 저장(setBridgeConfig) 후
//       곧바로 /recommend로 이동.

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { setBridgeConfig } from "../../lib/constants";

export default function AutoConnectPage() {
  const router = useRouter();
  const sp = useSearchParams();

  const [msg, setMsg] = useState("자동 연결 준비 중...");

  const bridgeBase = useMemo(() => (sp.get("bridge") || "").trim().replace(/\/$/, ""), [sp]);
  const token = useMemo(() => (sp.get("token") || "").trim(), [sp]);
  const next = useMemo(() => (sp.get("next") || "/recommend").trim() || "/recommend", [sp]);

  useEffect(() => {
    // bridge 파라미터가 없으면 저장할 게 없으니 그냥 이동
    if (!bridgeBase) {
      setMsg("bridge 파라미터가 없어서 Recommend로 이동합니다...");
      router.replace(next);
      return;
    }

    // localStorage 저장
    setBridgeConfig({ bridgeBase, bridgeToken: token });

    // URL에 토큰이 남지 않게 replace 이동
    setMsg("✅ 브릿지 설정 저장 완료. Recommend로 이동 중...");
    router.replace(next);
  }, [bridgeBase, token, next, router]);

  return (
    <div className="card">
      <div className="h1" style={{ fontSize: 22 }}>
        Auto Connect
      </div>
      <p className="p">{msg}</p>

      <div className="card" style={{ marginTop: 12 }}>
        <div className="h2">감지된 값</div>
        <div className="pre">
          {`bridgeBase: ${bridgeBase || "(empty)"}\nbridgeToken: ${token ? "(set)" : "(empty)"}\nnext: ${next}`}
        </div>
        <div className="p" style={{ marginTop: 10, opacity: 0.85 }}>
          * 이 페이지는 UI 없이 저장 후 바로 이동합니다. (Connect 페이지는 수동 설정/테스트용)
        </div>
      </div>
    </div>
  );
}
