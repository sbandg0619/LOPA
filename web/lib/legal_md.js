function escapeHtml(s) {
  return String(s || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function inline(mdLine) {
  let s = escapeHtml(mdLine);

  // links: [text](url)
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, `<a href="$2" target="_blank" rel="noreferrer">$1</a>`);

  // bold **text**
  s = s.replace(/\*\*([^*]+)\*\*/g, `<b>$1</b>`);

  // italic *text*  (너무 공격적으로 변환하지 않도록 최소)
  s = s.replace(/(^|[^*])\*([^*]+)\*(?!\*)/g, `$1<i>$2</i>`);

  // inline code `x`
  s = s.replace(/`([^`]+)`/g, `<code>$1</code>`);

  return s;
}

export function mdToHtml(md) {
  const lines = String(md || "").replace(/\r\n/g, "\n").split("\n");

  let html = "";
  let inUl = false;
  let inOl = false;
  let inCode = false;

  function closeLists() {
    if (inUl) { html += "</ul>"; inUl = false; }
    if (inOl) { html += "</ol>"; inOl = false; }
  }

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];

    // fenced code
    if (raw.trim().startsWith("```")) {
      if (!inCode) {
        closeLists();
        inCode = true;
        html += `<pre class="md_code"><code>`;
      } else {
        inCode = false;
        html += `</code></pre>`;
      }
      continue;
    }

    if (inCode) {
      html += escapeHtml(raw) + "\n";
      continue;
    }

    const line = raw.trimEnd();

    // empty line
    if (!line.trim()) {
      closeLists();
      html += `<div class="md_sp"></div>`;
      continue;
    }

    // headings
    if (/^###\s+/.test(line)) {
      closeLists();
      html += `<h3>${inline(line.replace(/^###\s+/, ""))}</h3>`;
      continue;
    }
    if (/^##\s+/.test(line)) {
      closeLists();
      html += `<h2>${inline(line.replace(/^##\s+/, ""))}</h2>`;
      continue;
    }
    if (/^#\s+/.test(line)) {
      closeLists();
      html += `<h1>${inline(line.replace(/^#\s+/, ""))}</h1>`;
      continue;
    }

    // blockquote
    if (/^>\s?/.test(line)) {
      closeLists();
      html += `<blockquote>${inline(line.replace(/^>\s?/, ""))}</blockquote>`;
      continue;
    }

    // ordered list: "1) " or "1. "
    if (/^\d+[\.\)]\s+/.test(line)) {
      if (!inOl) { closeLists(); inOl = true; html += "<ol>"; }
      html += `<li>${inline(line.replace(/^\d+[\.\)]\s+/, ""))}</li>`;
      continue;
    }

    // unordered list: "- " or "* "
    if (/^[-*]\s+/.test(line)) {
      if (!inUl) { closeLists(); inUl = true; html += "<ul>"; }
      html += `<li>${inline(line.replace(/^[-*]\s+/, ""))}</li>`;
      continue;
    }

    // paragraph
    closeLists();
    html += `<p>${inline(line)}</p>`;
  }

  if (inCode) html += `</code></pre>`;
  if (inUl) html += `</ul>`;
  if (inOl) html += `</ol>`;

  return html;
}
