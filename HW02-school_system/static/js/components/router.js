/**
 * Frontend router (v0.3.0).
 * Fetches HTML partials from /page/<subpath> and injects into #app-content.
 */

import { $ } from "../core/dom.js";
import { listAnnouncements } from "../core/api.js";

const ROUTE_TITLES = {
  "/page/home": "首頁",
  "/page/announcements": "公告列表",
  "/page/announcement/course-selection": "選課公告",
  "/page/announcement/paperless-transcript": "無紙化成績單公告",
  "/page/courses": "課程查詢",
  "/page/my-schedule": "我的課表",
  "/page/grades": "我的成績",
  "/page/transcript": "歷年成績單",
  "/page/teaching": "授課清單",
  "/page/grade-entry": "成績登錄",
  "/page/admin/menu": "選單管理",
  "/page/admin/announcements": "公告管理",
  "/page/admin/users": "帳號管理",
};

function escape(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

async function fetchPartial(route) {
  const res = await fetch(route, {
    headers: { "X-Requested-With": "fetch" },
    credentials: "same-origin",
  });
  if (res.status === 401) {
    // session expired — bounce to login page
    window.location.href = "/login";
    throw new Error("尚未登入，正在跳轉登入頁…");
  }
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.text();
}

function setTitleFromContent(content, fallback) {
  // Prefer an explicit <h1 data-page-title> in the partial; fall back to first <h1>.
  const explicit = content.querySelector("[data-page-title]");
  const heading = explicit || content.querySelector("h1");
  const title = (heading?.textContent || fallback || "頁面").trim();
  document.title = `${title} — 校務資訊系統`;
  return title;
}

function showLoading(route) {
  const content = $("#app-content");
  if (!content) return;
  content.innerHTML = `<p class="muted">載入 <code>${escape(route)}</code>…</p>`;
}

function showError(route, err) {
  const content = $("#app-content");
  if (!content) return;
  content.innerHTML = `
    <section class="card">
      <h2>載入失敗</h2>
      <p class="muted">${escape(err.message || String(err))}</p>
      <button class="btn btn-ghost" type="button" data-retry="${escape(route)}">重試</button>
    </section>
  `;
  const btn = content.querySelector("[data-retry]");
  if (btn) btn.addEventListener("click", () => navigate(route));
}

export function initRouter({ content, sidebar } = {}) {
  if (!content) return;

  async function navigate(route, { pushState = true } = {}) {
    console.info("[router] navigate ->", route);
    showLoading(route);
    if (sidebar) sidebar.setActive(route);
    if (pushState) history.pushState({ route }, "", route);
    try {
      const html = await fetchPartial(route);
      console.info("[router] fetched", route, html.length, "bytes");
      content.innerHTML = html;
      setTitleFromContent(content, ROUTE_TITLES[route]);
      content.dispatchEvent(new CustomEvent("nku:content-loaded", { detail: { route } }));
    } catch (err) {
      console.warn("[router] failed", route, err);
      showError(route, err);
    }
  }

  window.addEventListener("nku:navigate", (e) => {
    const route = e.detail?.route;
    if (route) navigate(route);
  });

  // intercept clicks inside content that have data-route (so inner links navigate)
  content.addEventListener("click", (e) => {
    const link = e.target.closest("a[data-route]");
    if (!link) return;
    const route = link.getAttribute("data-route");
    if (!route || !route.startsWith("/page/")) return;
    e.preventDefault();
    navigate(route);
  });

  window.addEventListener("popstate", () => {
    const route = window.location.pathname;
    if (sidebar) sidebar.setActive(route);
    navigate(route, { pushState: false });
  });

  // Set initial title from the loaded partial (called once by app.js).
  return { navigate, setTitleFromContent };
}

export async function loadDefaultAnnouncementsInto(content) {
  const items = await listAnnouncements();
  content.innerHTML = `<div class="announcement-list">${items.slice(0, 4).map((a) => `
    <article class="announcement-card">
      <span class="badge">${escape(a.category)}</span>
      <h3>${escape(a.title)}</h3>
      <p class="preview">${escape((a.content || "").slice(0, 80))}…</p>
      <div class="actions">
        <a class="btn btn-outline" href="/page/announcement/${encodeURIComponent(a.slug)}" data-route="/page/announcement/${encodeURIComponent(a.slug)}">閱讀全文</a>
      </div>
    </article>
  `).join("")}</div>`;
}