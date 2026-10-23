// Admin menu CRUD page.
import { $ } from "../core/dom.js";

function escape(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function buildAdminTree(nodes, depth = 0) {
  const ul = document.createElement("ul");
  ul.className = "admin-tree";
  if (depth > 0) ul.classList.add("admin-tree-nested");
  for (const node of nodes) {
    const li = document.createElement("li");
    li.dataset.id = String(node.id);
    const hasChildren = (node.children || []).length > 0;
    li.innerHTML = `
      <div class="admin-tree-row">
        <button class="admin-tree-caret" type="button" aria-expanded="true">▶</button>
        <button class="admin-tree-label" type="button" data-action="edit"
                data-id="${node.id}">
          ${escape(node.label)} <small class="muted">#${node.id} · ${escape(node.required_role)}</small>
        </button>
        <button class="admin-tree-add" type="button" data-action="add-child"
                data-id="${node.id}" title="新增子節點">＋</button>
      </div>
    `;
    if (hasChildren) {
      li.appendChild(buildAdminTree(node.children, depth + 1));
    } else {
      li.classList.add("admin-tree-leaf");
    }
    ul.appendChild(li);
  }
  return ul;
}

function findNodeById(nodes, id) {
  for (const n of nodes) {
    if (n.id === id) return n;
    if (n.children) {
      const r = findNodeById(n.children, id);
      if (r) return r;
    }
  }
  return null;
}

async function fetchMenu() {
  const res = await fetch("/api/admin/menu", { credentials: "same-origin" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  window.__adminMenuCache = data.menu;
  return data.menu;
}

async function loadAndRender() {
  const container = $("#admin-menu-tree");
  if (!container) return;
  container.innerHTML = `<p class="muted">載入中…</p>`;
  try {
    const menu = await fetchMenu();
    container.innerHTML = "";
    container.appendChild(buildAdminTree(menu));
  } catch (err) {
    container.innerHTML = `<p class="muted">載入失敗：${escape(err.message)}</p>`;
  }
}

function fillForm(item) {
  const form = $("#admin-menu-form");
  if (!form) return;
  form.elements.id.value = item?.id || "";
  form.elements.label.value = item?.label || "";
  form.elements.route.value = item?.route || "";
  form.elements.icon.value = item?.icon || "";
  form.elements.sort_order.value = item?.sort_order ?? 0;
  form.elements.required_role.value = item?.required_role || "student";
  form.elements.parent_id.value = item?.parent_id ?? "";
  $("#admin-form-title").textContent = item ? `編輯節點 #${item.id}` : "新增選單節點";
  $("#admin-form-delete").hidden = !item;
}

function showError(msg) {
  const box = document.querySelector("#admin-menu-form [data-role='error']");
  if (!box) return;
  box.textContent = msg || "";
  box.hidden = !msg;
}

export async function initAdminMenu() {
  const form = $("#admin-menu-form");
  if (!form) return;

  await loadAndRender();

  $("#admin-refresh").addEventListener("click", loadAndRender);
  $("#admin-add-root").addEventListener("click", () => fillForm(null));

  $("#admin-menu-tree").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-action]");
    if (btn?.dataset.action === "edit") {
      const node = findNodeById(window.__adminMenuCache || [], Number(btn.dataset.id));
      fillForm(node || { id: Number(btn.dataset.id) });
    } else if (btn?.dataset.action === "add-child") {
      fillForm({ parent_id: Number(btn.dataset.id), required_role: "student", sort_order: 0 });
    }
    const caret = e.target.closest(".admin-tree-caret");
    if (caret) {
      const li = caret.closest("li");
      const nested = li?.querySelector(".admin-tree-nested");
      if (nested) {
        const isOpen = caret.getAttribute("aria-expanded") !== "false";
        caret.setAttribute("aria-expanded", String(!isOpen));
        nested.style.display = isOpen ? "none" : "";
      }
    }
  });

  $("#admin-form-reset").addEventListener("click", () => fillForm(null));

  $("#admin-form-delete").addEventListener("click", async () => {
    const id = form.elements.id.value;
    if (!id) return;
    if (!confirm(`確定刪除節點 #${id}？（子節點會一併刪除）`)) return;
    const res = await fetch(`/api/admin/menu/${id}`, { method: "DELETE", credentials: "same-origin" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showError(err.error || `HTTP ${res.status}`);
      return;
    }
    fillForm(null);
    await loadAndRender();
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    showError("");
    const fd = new FormData(form);
    const payload = {
      label: fd.get("label"),
      route: fd.get("route") || null,
      icon: fd.get("icon") || null,
      sort_order: Number(fd.get("sort_order") || 0),
      required_role: fd.get("required_role"),
      parent_id: fd.get("parent_id") ? Number(fd.get("parent_id")) : null,
    };
    const id = fd.get("id");
    const url = id ? `/api/admin/menu/${id}` : "/api/admin/menu";
    const method = id ? "PUT" : "POST";
    const res = await fetch(url, {
      method,
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
    await loadAndRender();
  });
}