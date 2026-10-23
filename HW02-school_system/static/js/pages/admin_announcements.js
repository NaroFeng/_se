// Admin announcement CMS page.
import { $ } from "../core/dom.js";

function escape(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function showError(msg) {
  const box = document.querySelector("#admin-ann-form [data-role='error']");
  if (!box) return;
  box.textContent = msg || "";
  box.hidden = !msg;
}

function fillForm(item) {
  const form = $("#admin-ann-form");
  if (!form) return;
  form.elements.slug.value = item?.slug || "";
  form.elements.slug.disabled = Boolean(item);
  form.elements.title.value = item?.title || "";
  form.elements.category.value = item?.category || "";
  form.elements.issued_at.value = item?.issued_at || "";
  form.elements.author.value = item?.author || "";
  form.elements.content.value = item?.content || "";
  $("#admin-ann-form-title").textContent = item ? `編輯公告：${item.title}` : "新增公告";
  $("#admin-ann-delete").hidden = !item;
}

async function fetchAnnouncements() {
  const res = await fetch("/api/admin/announcements", { credentials: "same-origin" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()).announcements;
}

async function loadAndRenderList() {
  const list = $("#admin-ann-list");
  if (!list) return;
  list.innerHTML = `<li class="muted">載入中…</li>`;
  try {
    const items = await fetchAnnouncements();
    window.__adminAnnCache = items;
    if (!items.length) {
      list.innerHTML = `<li class="muted">目前沒有公告</li>`;
      return;
    }
    list.innerHTML = "";
    for (const a of items) {
      const li = document.createElement("li");
      li.className = "admin-list-item";
      li.innerHTML = `
        <button class="admin-list-btn" type="button" data-slug="${escape(a.slug)}">
          <strong>${escape(a.title)}</strong>
          <small class="muted">${escape(a.category || "")} · ${escape(a.issued_at || "")}</small>
        </button>
      `;
      list.appendChild(li);
    }
  } catch (err) {
    list.innerHTML = `<li class="muted">載入失敗：${escape(err.message)}</li>`;
  }
}

export async function initAdminAnnouncements() {
  const form = $("#admin-ann-form");
  if (!form) return;

  await loadAndRenderList();

  $("#admin-ann-refresh").addEventListener("click", loadAndRenderList);
  $("#admin-ann-new").addEventListener("click", () => fillForm(null));

  $("#admin-ann-list").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-slug]");
    if (!btn) return;
    const slug = btn.dataset.slug;
    const item = (window.__adminAnnCache || []).find((a) => a.slug === slug);
    if (item) fillForm(item);
  });

  $("#admin-ann-reset").addEventListener("click", () => fillForm(null));

  $("#admin-ann-delete").addEventListener("click", async () => {
    const slug = form.elements.slug.value;
    if (!slug) return;
    if (!confirm(`確定刪除公告「${slug}」？`)) return;
    const res = await fetch(`/api/admin/announcements/${encodeURIComponent(slug)}`, {
      method: "DELETE",
      credentials: "same-origin",
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showError(err.error || `HTTP ${res.status}`);
      return;
    }
    fillForm(null);
    await loadAndRenderList();
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    showError("");
    const fd = new FormData(form);
    const payload = {
      slug: (fd.get("slug") || "").toString().trim(),
      title: (fd.get("title") || "").toString().trim(),
      category: (fd.get("category") || "").toString().trim(),
      issued_at: (fd.get("issued_at") || "").toString().trim(),
      author: (fd.get("author") || "").toString().trim(),
      content: (fd.get("content") || "").toString(),
    };
    const res = await fetch("/api/admin/announcements", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showError(data.error || `HTTP ${res.status}`);
      return;
    }
    fillForm(null);
    await loadAndRenderList();
  });
}