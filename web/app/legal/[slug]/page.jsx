"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { mdToHtml } from "../../../lib/legal_md";

// 허용 slug 화이트리스트 (이 목록 외에는 "문서 없음" 처리)
const ALLOWED = new Set([
  "terms_ko",
  "privacy_ko",
  "disclaimer_ko",
  "deletion_ko",
  "contact_ko",
  "terms_en",
  "privacy_en",
  "disclaimer_en",
  "deletion_en",
  "contact_en",
]);

export default function LegalDocPage({ params }) {
  const slug = String(params?.slug || "").trim();

  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [md, setMd] = useState("");

  const isAllowed = useMemo(() => ALLOWED.has(slug), [slug]);

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      setErr("");
      setMd("");

      if (!slug) {
        setErr("invalid slug");
        setLoading(false);
        return;
      }
      if (!isAllowed) {
        setErr("not found");
        setLoading(false);
        return;
      }

      try {
        const r = await fetch(`/api/legal?name=${encodeURIComponent(slug)}`, { cache: "no-store" });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const txt = await r.text();
        if (!alive) return;
        setMd(txt);
      } catch (e) {
        if (!alive) return;
        setErr(String(e?.message || e));
      } finally {
        if (!alive) return;
        setLoading(false);
      }
    })();

    return () => { alive = false; };
  }, [slug, isAllowed]);

  const html = useMemo(() => mdToHtml(md), [md]);

  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <div className="h1" style={{ marginBottom: 4 }}>Legal — {slug || "(empty)"}</div>
          <p className="p" style={{ marginTop: 0 }}>
            {loading ? "loading..." : err ? `error: ${err}` : "loaded"}
          </p>
        </div>

        <div className="row">
          <Link className="btn" href="/legal">Legal 목록</Link>
        </div>
      </div>

      <div style={{ height: 10 }} />

      {loading ? (
        <div className="p">문서 로딩 중...</div>
      ) : err ? (
        <div className="card" style={{ background: "rgba(255,0,0,0.06)" }}>
          <div className="h2">문서를 불러오지 못함</div>
          <div className="p">slug: {slug || "(empty)"}</div>
          {err === "not found" ? (
            <div className="p">해결: /legal 목록에서 존재하는 문서를 선택해 주세요.</div>
          ) : (
            <div className="p">
              해결: legal 폴더를 <b>web/public/legal</b> 로 복사한 뒤 다시 시도.
            </div>
          )}
          <div style={{ height: 10 }} />
          <Link className="btn" href="/legal">Legal 목록으로</Link>
        </div>
      ) : (
        <div className="md" dangerouslySetInnerHTML={{ __html: html }} />
      )}
    </div>
  );
}
