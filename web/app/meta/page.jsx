"use client";

// web/app/meta/page.jsx
// 목적: 추천이 빈 배열일 때(패치/티어/DB 문제) 바로 진단 가능하게
// - API /health, /meta를 UI에서 확인
// - db_path를 바꿔가며 "latest_patch / patches" 확인 가능

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiHealth, apiMeta } from "../../lib/api";

export default function MetaPage() {
  const [dbPath, setDbPath] = useState("lol_graph_personal.db");

  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [health, setHealth] = useState(null);
  const [meta, setMeta] = useState(null);

  async function runAll() {
    setErr("");
    setLoading(true);
    setHealth(null);
    setMeta(null);
    try {
      const h = await apiHealth();
      setHealth(h);

      const m = await apiMeta(dbPath);
      setMeta(m);
    } catch (e) {
      setErr(String(e?.message || e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    runAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <div className="h1">Meta (API 진단)</div>
          <p className="p" style={{ margin: 0 }}>
            추천이 비어있을 때 가장 먼저 확인할 것: <b>API가 보는 DB</b> / <b>latest_patch</b> / <b>patch 목록</b>.
          </p>
        </div>
        <div className="row">
          <Link className="btn" href="/recommend">
            Recommend →
          </Link>
        </div>
      </div>

      <div style={{ height: 12 }} />

      <div className="card">
        <div className="h2">DB 선택</div>
        <div className="row" style={{ marginTop: 8 }}>
          <div style={{ flex: 1, minWidth: 260 }}>
            <div className="p" style={{ fontWeight: 800 }}>
              db_path
            </div>
            <input className="input" value={dbPath} onChange={(e) => setDbPath(e.target.value)} />
          </div>
          <button className="btn" onClick={runAll} disabled={loading}>
            {loading ? "Loading..." : "Refresh"}
          </button>
        </div>
        {err ? <div style={{ marginTop: 10, fontWeight: 900 }}>❌ {err}</div> : null}
      </div>

      <div style={{ height: 12 }} />

      <div className="grid">
        <div className="card">
          <div className="h2">API /health</div>
          <div className="p">API 프로파일/기본 DB를 확인.</div>
          {health ? <div className="pre">{JSON.stringify(health, null, 2)}</div> : <div className="p">(empty)</div>}
        </div>

        <div className="card">
          <div className="h2">API /meta</div>
          <div className="p">
            DB 기준 최신 패치/패치 목록 확인. (Recommend의 patch 입력/ALL 처리 이슈를 여기서 바로 잡음)
          </div>
          {meta ? <div className="pre">{JSON.stringify(meta, null, 2)}</div> : <div className="p">(empty)</div>}
        </div>
      </div>

      <div className="card" style={{ marginTop: 12 }}>
        <div className="h2">빠른 체크 포인트</div>
        <ul className="p" style={{ lineHeight: 1.8 }}>
          <li>
            meta.latest_patch가 <b>null</b>이면: matches 테이블에 patch/game_creation이 비어있거나 데이터가 없을 수 있음.
          </li>
          <li>
            meta.patches에 원하는 패치가 없다면: Recommend에서 patch를 넣어도 필터에 걸려 recs가 비기 쉬움.
          </li>
          <li>
            추천이 비면: (1) patch/tier를 ALL로 (2) min_games를 1~5로 낮추고 테스트.
          </li>
        </ul>
      </div>
    </div>
  );
}
