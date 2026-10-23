import { $, $$ } from "../core/dom.js";

const SIDEBAR_STATE_KEY = "nku.sidebar.hidden";

function setSidebarHidden(hidden) {
  const shell = $("#app-shell");
  const btn = $("#toggle-sidebar-btn");
  if (!shell || !btn) return;
  shell.dataset.sidebar = hidden ? "hidden" : "visible";
  btn.dataset.action = hidden ? "show" : "hide";
  btn.textContent = hidden ? "顯示選單" : "隱藏選單";
  try { localStorage.setItem(SIDEBAR_STATE_KEY, hidden ? "1" : "0"); } catch { /* noop */ }
}

export function initHeader() {
  const btn = $("#toggle-sidebar-btn");
  if (btn) {
    btn.addEventListener("click", () => {
      const hidden = btn.dataset.action === "hide";
      setSidebarHidden(hidden);
    });
    try {
      if (localStorage.getItem(SIDEBAR_STATE_KEY) === "1") {
        setSidebarHidden(true);
      }
    } catch { /* noop */ }
  }

  const logoutForm = $("#logout-form");
  if (logoutForm) {
    logoutForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
      } finally {
        window.location.href = "/login";
      }
    });
  }

  const pwBtn = $("#change-password-btn");
  const modal = $("#change-password-modal");
  if (pwBtn && modal) {
    pwBtn.addEventListener("click", () => {
      if (typeof modal.showModal === "function") modal.showModal();
      else modal.setAttribute("open", "");
    });
  }
}