import { $ } from "./core/dom.js";
import { initHeader } from "./components/header.js";
import { initChangePasswordModal } from "./components/modal.js";
import { initSidebar } from "./components/sidebar.js";
import { initRouter } from "./components/router.js";
import { switchRole } from "./core/api.js";
import { initAdminMenu } from "./pages/admin_menu.js";
import { initAdminAnnouncements } from "./pages/admin_announcements.js";
import { initAdminUsers } from "./pages/admin_users.js";

document.addEventListener("DOMContentLoaded", () => {
  initHeader();
  initChangePasswordModal();

  const sidebar = initSidebar({
    onNavigate: (node) => window.dispatchEvent(new CustomEvent("nku:navigate", { detail: { route: node.route, node } })),
  });
  if (sidebar) window.__nkuSidebar = sidebar;

  const content = $("#app-content");
  const router = initRouter({ content, sidebar });

  // If the server pre-rendered a partial (direct visit to /page/...),
  // honour it instead of re-fetching /page/home.
  if (router && content && window.__initialRoute) {
    const initial = window.__initialRoute;
    delete window.__initialRoute;
    if (sidebar) sidebar.setActive(initial);
    history.replaceState({ route: initial }, "", initial);
    // Update title from the embedded H1.
    const h1 = content.querySelector("h1");
    if (h1) document.title = `${h1.textContent.trim()} — 校務資訊系統`;
    content.dispatchEvent(new CustomEvent("nku:content-loaded", { detail: { route: initial } }));
  } else if (router && content && content.querySelector("[data-page='home']")) {
    router.navigate("/page/home", { pushState: false });
  }

  // Role switcher inside partial pages.
  content.addEventListener("change", async (e) => {
    if (e.target && e.target.id === "role-switcher") {
      const role = e.target.value;
      try {
        await switchRole(role);
        if (sidebar) await sidebar.load();
        router.navigate("/page/home", { pushState: false });
      } catch (err) {
        alert("切換失敗：" + err.message);
      }
    }
  });

  // Admin page initialisers — dispatched after content swap.
  content.addEventListener("nku:content-loaded", async (e) => {
    const route = e.detail?.route;
    if (route === "/page/admin/menu") {
      await initAdminMenu();
    } else if (route === "/page/admin/announcements") {
      await initAdminAnnouncements();
    } else if (route === "/page/admin/users") {
      await initAdminUsers();
    } else if (route?.startsWith("/page/admin/menu") && sidebar) {
      // changed admin menu: refresh sidebar
      await sidebar.load();
    } else if (route?.startsWith("/page/admin/announcements") && sidebar) {
      // nothing extra
    }
  });

  console.info("[NKU portal] v0.4.0 ready");
});