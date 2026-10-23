import { $ } from "../core/dom.js";
import { getMenu } from "../core/api.js";
import { storage } from "../core/storage.js";
import { buildTree, filterTree, collectMatchingIds } from "../utils/tree.js";
import { highlightToHtml } from "../utils/highlight.js";

const EXPANDED_KEY = "sidebar.expanded.v1";
const ACTIVE_KEY = "sidebar.active.v1";
const HIDDEN_KEY = "sidebar.hidden.v1";

const ICONS = {
  home: "🏠",
  megaphone: "📣",
  book: "📚",
  grade: "🏆",
  tools: "🛠️",
  shield: "🛡️",
  doc: "📄",
  list: "📋",
  search: "🔍",
  calendar: "📅",
  trophy: "🏅",
  edit: "✏️",
  menu: "🧭",
  user: "👤",
  // 選課 / 教務 / 學務
  course: "🎓",
  add: "➕",
  plus: "✚",
  minus: "➖",
  result: "📊",
  stop: "🛑",
  general: "📚",
  manual: "✍️",
  over: "⬆️",
  under: "⬇️",
  program: "📘",
  warning: "⚠️",
  history: "🕓",
  waiver: "🔁",
  info: "ℹ️",
  plan: "🗺️",
  teacher: "👨‍🏫",
  room: "🏫",
  class: "👥",
  audit: "✅",
  reply: "↩️",
  leave: "🚪",
  cross: "🔀",
  micro: "🔬",
  minor: "🎭",
  affairs: "🏛️",
  attendance: "📅",
  reward: "🏅",
  money: "💰",
  army: "🪖",
  people: "👥",
};

function iconFor(name) {
  return ICONS[name] || "•";
}

export class Sidebar {
  constructor(navEl, searchEl, { onNavigate } = {}) {
    this.nav = navEl;
    this.search = searchEl;
    this.onNavigate = onNavigate || (() => {});
    this.tree = [];
    this.expanded = new Set(storage.get(EXPANDED_KEY, []));
    this.active = storage.get(ACTIVE_KEY, null);
    this.query = "";
  }

  async load() {
    try {
      console.info("[sidebar] loading menu from /api/menu...");
      const flat = await getMenu();
      console.info("[sidebar] got", flat.length, "items");
      this.tree = buildTree(flat);
    } catch (err) {
      console.error("[sidebar] failed to load menu:", err);
      // Keep any server-rendered content; just append a warning.
      const banner = document.createElement("p");
      banner.className = "sidebar-error";
      banner.textContent = `即時互動載入失敗（${err.message}），顯示為伺服器預渲染版本。`;
      this.nav.prepend(banner);
      return;
    }
    this.render();
    this.applyActiveClass();
    console.info("[sidebar] rendered", this.nav.querySelectorAll(".menu-node").length, "nodes");
  }

  render() {
    this.nav.innerHTML = "";
    const visible = filterTree(this.tree, this.query);
    const visibleIds = collectMatchingIds(this.flatten(this.tree), this.query);
    const ul = this.renderNodes(visible, 0, visibleIds);
    this.nav.appendChild(ul);
  }

  flatten(tree) {
    const out = [];
    function walk(nodes) {
      for (const n of nodes) {
        out.push(n);
        walk(n.children || []);
      }
    }
    walk(tree);
    return out;
  }

  renderNodes(nodes, depth, visibleIds) {
    const ul = document.createElement("ul");
    ul.className = "menu-tree";
    ul.setAttribute("role", "tree");
    if (depth > 0) ul.classList.add("menu-children");
    ul.dataset.depth = String(depth);

    for (const node of nodes) {
      ul.appendChild(this.renderNode(node, depth, visibleIds));
    }
    return ul;
  }

  renderNode(node, depth, visibleIds) {
    const li = document.createElement("li");
    li.className = "menu-node";
    li.setAttribute("role", "treeitem");
    li.dataset.nodeId = String(node.id);

    const hasChildren = (node.children || []).length > 0;
    const isExpanded = this.expanded.has(node.id) || (this.query && visibleIds.has(node.id));
    const labelHtml = highlightToHtml(node.label, this.query);

    if (hasChildren && !node.route) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "menu-toggle";
      btn.setAttribute("aria-expanded", String(isExpanded));
      btn.innerHTML = `
        <span class="menu-caret" aria-hidden="true">▶</span>
        <span class="menu-icon" aria-hidden="true">${iconFor(node.icon)}</span>
        <span class="menu-label">${labelHtml}</span>
      `;
      btn.addEventListener("click", () => this.toggle(node.id));
      li.appendChild(btn);
    } else {
      const a = document.createElement("a");
      a.className = "menu-link";
      a.href = node.route || "#";
      a.dataset.route = node.route || "";
      a.innerHTML = `
        <span class="menu-icon" aria-hidden="true">${iconFor(node.icon)}</span>
        <span class="menu-label">${labelHtml}</span>
      `;
      a.addEventListener("click", (e) => this.handleLinkClick(e, node));
      li.appendChild(a);
      console.debug("[sidebar] link", node.route, node.label);
    }

    if (hasChildren) {
      const childUl = this.renderNodes(node.children, depth + 1, visibleIds);
      if (!isExpanded) childUl.classList.add("menu-collapsed");
      li.appendChild(childUl);
    }

    return li;
  }

  toggle(id) {
    if (this.expanded.has(id)) this.expanded.delete(id);
    else this.expanded.add(id);
    storage.set(EXPANDED_KEY, Array.from(this.expanded));
    this.render();
    this.applyActiveClass();
  }

  handleLinkClick(event, node) {
    if (!node.route) return;
    console.info("[sidebar] click", node.route, node.label);
    this.active = node.route;
    storage.set(ACTIVE_KEY, this.active);
    this.applyActiveClass();
    if (this.onNavigate) {
      event.preventDefault();
      console.info("[sidebar] preventDefault + onNavigate", node.route);
      this.onNavigate(node);
    } else {
      console.warn("[sidebar] no onNavigate callback");
    }
  }

  applyActiveClass() {
    this.nav.querySelectorAll(".menu-link.active").forEach((el) => el.classList.remove("active"));
    if (!this.active) return;
    const target = this.nav.querySelector(`[data-route="${CSS.escape(this.active)}"]`);
    if (target) target.classList.add("active");
  }

  applySearch(query) {
    this.query = query || "";
    this.render();
    this.applyActiveClass();
  }

  setActive(route) {
    this.active = route;
    storage.set(ACTIVE_KEY, route);
    this.applyActiveClass();
  }
}

export function initSidebar({ onNavigate } = {}) {
  const nav = $("#sidebar-nav");
  const search = $("#sidebar-search");
  if (!nav) return null;

  const sidebar = new Sidebar(nav, search, { onNavigate });

  if (search) {
    search.disabled = false;
    search.addEventListener("input", (e) => sidebar.applySearch(e.target.value));
    search.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        search.value = "";
        sidebar.applySearch("");
      }
    });
  }

  sidebar.load();
  return sidebar;
}

export const __sidebarConstants = { EXPANDED_KEY, ACTIVE_KEY, HIDDEN_KEY };