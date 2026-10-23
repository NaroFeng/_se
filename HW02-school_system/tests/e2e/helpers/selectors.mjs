/**
 * Centralised DOM selectors. Kept stable so spec files stay readable
 * even when templates change structure.
 *
 * Note: Playwright does NOT support :has-text() in CSS selectors — use
 * locator.filter({ has: ... }) at the call site for contextual matching.
 */

export const SEL = {
  loginForm: "#login-form",
  loginUsername: "input[name='username']",
  loginPassword: "input[name='password']",
  loginSubmit: "#login-form button[type='submit']",
  loginError: ".login-error",

  sidebar: "#sidebar",
  sidebarNav: "#sidebar-nav",
  sidebarSearch: "#sidebar-search",
  sidebarMenuNodes: "#sidebar-nav .menu-node",
  sidebarLinkByRoute: (route) => `#sidebar-nav a[data-route='${route}']`,
  sidebarLinkByLabel: (label) => `#sidebar-nav a:has(.menu-label:text-is("${label}"))`,
  // Match any label whether it's inside an <a> link or a <button> folder toggle.
  sidebarItemByLabel: (label) => `#sidebar-nav .menu-label:text-is("${label}")`,
  sidebarToggle: "#sidebar-nav .menu-toggle",
  sidebarHighlight: "#sidebar-nav mark",

  header: ".app-header",
  changePasswordBtn: "#change-password-btn",
  changePasswordModal: "#change-password-modal",
  changePasswordOld: "input[name='old_password']",
  changePasswordNew: "input[name='new_password']",
  changePasswordConfirm: "input[name='confirm_password']",
  changePasswordSubmit: "#change-password-submit",
  changePasswordError: "#change-password-modal [data-role='error']",

  toggleSidebarBtn: "#toggle-sidebar-btn",
  logoutForm: "#logout-form",
  logoutBtn: "#logout-form button[type='submit']",

  appContent: "#app-content",

  // Announcement admin
  adminAnnList: "#admin-ann-list",
  adminAnnForm: "#admin-ann-form",
  adminAnnNewBtn: "#admin-ann-new",
  adminAnnSaveBtn: "#admin-ann-form button[type='submit']",
  adminAnnDeleteBtn: "#admin-ann-delete",
  adminAnnResetBtn: "#admin-ann-reset",
  adminAnnItemBySlug: (slug) => `#admin-ann-list button[data-slug='${slug}']`,

  // Users admin
  usersToolbar: ".users-toolbar",
  usersSearch: "#users-search",
  usersFilterRole: "#users-filter-role",
  usersFilterStatus: "#users-filter-status",
  usersFilterDept: "#users-filter-department",
  usersRefresh: "#users-refresh",
  usersExport: "#users-export",
  usersDownloadTemplate: "#users-download-template",
  usersImportFile: "#users-import-file",
  usersNew: "#users-new",
  usersTable: ".users-table",
  usersTbody: "#users-tbody",
  usersRowByUsername: (username) =>
    `#users-tbody tr:has(code:text-is("${username}"))`,
  usersSummary: "#users-summary",
  usersPrev: "#users-prev",
  usersNext: "#users-next",
  usersPageInfo: "#users-page-info",
  usersDrawer: "#users-drawer",
  usersDrawerTitle: "#users-drawer-title",
  usersForm: "#users-form",
  usersFormSubmit: "#users-form button[type='submit']",
  resetPwModal: "#reset-pw-modal",
  resetPwSubmit: "#reset-pw-submit",
  resetPwUsername: "#reset-pw-username",
};

/** Default seed accounts (data/seed_users.json). */
export const ACCOUNTS = {
  student: { username: "s114210501", password: "pass1234" },
  student2: { username: "s114210502", password: "pass1234" },
  teacher: { username: "teacher01", password: "pass1234" },
  admin: { username: "admin", password: "admin1234" },
};
