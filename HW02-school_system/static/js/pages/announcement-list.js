import { $ } from "../core/dom.js";
import { listAnnouncements } from "../core/api.js";

/**
 * v0.1.0 announcement list: fetches /api/announcements and renders cards.
 * v0.3.0 will plug this into the router.
 */
export function mountAnnouncementList(container) {
  if (!container) return;
  container.innerHTML = `<p class="muted">載入公告中...</p>`;
  listAnnouncements()
    .then((items) => {
      if (!items.length) {
        container.innerHTML = `<p class="muted">目前沒有公告。</p>`;
        return;
      }
      container.innerHTML = "";
      for (const a of items) {
        const card = document.createElement("article");
        card.className = "announcement-card";
        const preview = (a.content || "").replace(/[#>*_`]/g, "").slice(0, 90);
        card.innerHTML = `
          <span class="meta">${escape(a.category)} · ${escape(a.issued_at)}</span>
          <h3>${escape(a.title)}</h3>
          <p class="preview">${escape(preview)}…</p>
          <div class="actions">
            <a class="btn btn-outline" href="/page/announcement/${encodeURIComponent(a.slug)}">閱讀全文</a>
          </div>
        `;
        container.appendChild(card);
      }
    })
    .catch((err) => {
      container.innerHTML = `<p class="muted">載入失敗：${escape(err.message)}</p>`;
    });
}

function escape(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}