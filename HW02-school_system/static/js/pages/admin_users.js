// Admin user management page.
import { $ } from "../core/dom.js";

function escape(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

const state = {
  page: 1,
  per_page: 20,
  search: "",
  role: "",
  status: "",
  department_id: "",
  total: 0,
  pages: 0,
  resetTargetId: null,
  departments: [],
};

async function fetchDepartments() {
  const res = await fetch("/api/admin/departments", { credentials: "same-origin" });
  if (!res.ok) throw new Error(`departments HTTP ${res.status}`);
  return (await res.json()).departments;
}

function populateDepartmentSelect(selectEl, includeEmpty = true) {
  if (!selectEl) return;
  const current = selectEl.value;
  selectEl.innerHTML =
    (includeEmpty ? `<option value="">— 全部系所 —</option>` : `<option value="">— 無 —</option>`) +
    state.departments.map((d) =>
      `<option value="${d.id}">${escape(d.code)} — ${escape(d.name)}</option>`
    ).join("");
  if (current) selectEl.value = current;
}

async function fetchUsers() {
  const params = new URLSearchParams({ page: state.page, per_page: state.per_page });
  if (state.search) params.set("q", state.search);
  if (state.role) params.set("role", state.role);
  if (state.status) params.set("status", state.status);
  if (state.department_id) params.set("department_id", state.department_id);
  const res = await fetch(`/api/admin/users?${params}`, { credentials: "same-origin" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function renderTable(items) {
  const tbody = $("#users-tbody");
  if (!items.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="muted">無符合條件的人員</td></tr>`;
    return;
  }
  tbody.innerHTML = items.map((u) => {
    const grade = u.current_grade ? `${u.current_grade} 年級` : "—";
    const dept = u.dept_name || u.department || "—";
    return `
    <tr data-id="${u.id}">
      <td><code>${escape(u.username)}</code>${u.student_id && u.student_id !== u.username
          ? `<br><small class="muted">學號：${escape(u.student_id)}</small>` : ""}</td>
      <td>${escape(u.display_name)}</td>
      <td>${escape(dept)}${u.dept_code ? ` <small class="muted">(${escape(u.dept_code)})</small>` : ""}</td>
      <td>${escape(grade)}</td>
      <td>${escape(u.class_name) || "—"}</td>
      <td><span class="badge badge-role-${escape(u.role)}">${escape(u.role)}</span></td>
      <td>${statusBadge(u.status)}</td>
      <td class="muted">${escape(u.email) || "—"}</td>
      <td class="row-actions">
        <button class="btn btn-ghost btn-sm" type="button" data-action="edit">編輯</button>
        <button class="btn btn-ghost btn-sm" type="button" data-action="reset-pw">重設密碼</button>
        <button class="btn btn-outline btn-sm" type="button" data-action="delete">刪除</button>
      </td>
    </tr>
  `;}).join("");
}

function statusBadge(status) {
  switch (status) {
    case "active": return '<span class="badge badge-success">啟用</span>';
    case "disabled": return '<span class="badge badge-warning">停用</span>';
    case "graduated": return '<span class="badge">畢業</span>';
    case "suspended": return '<span class="badge badge-role-admin">暫停</span>';
    default: return `<span class="badge">${escape(status)}</span>`;
  }
}

function renderPager() {
  $("#users-page-info").textContent = `第 ${state.page} / ${state.pages || 1} 頁，共 ${state.total} 筆`;
  $("#users-prev").disabled = state.page <= 1;
  $("#users-next").disabled = state.page >= state.pages;
}

function showError(msg) {
  const box = document.querySelector(".admin-users [data-role='error']");
  if (!box) return;
  box.textContent = msg || "";
  box.hidden = !msg;
}

async function loadAndRender() {
  showError("");
  try {
    const data = await fetchUsers();
    state.total = data.total;
    state.pages = data.pages;
    renderTable(data.items);
    renderPager();
    const filters = [
      state.search || null,
      state.role ? `角色=${state.role}` : null,
      state.status ? `狀態=${state.status}` : null,
      state.department_id ? `系所=#${state.department_id}` : null,
    ].filter(Boolean).join("、") || "（無）";
    $("#users-summary").textContent = `顯示 ${data.items.length} / ${data.total} 筆，篩選：${filters}`;
  } catch (err) {
    showError("載入失敗：" + err.message);
  }
}

function toggleStudentsOnly(role) {
  const fset = $("#students-only");
  if (!fset) return;
  fset.style.display = role === "student" ? "" : "none";
}

function openDrawer(user) {
  const drawer = $("#users-drawer");
  const form = $("#users-form");
  const title = $("#users-drawer-title");
  const pwHint = $("#users-pwd-hint");
  form.reset();
  const errBox = form.querySelector("[data-role='form-error']");
  if (errBox) { errBox.textContent = ""; errBox.hidden = true; }
  populateDepartmentSelect($("#users-form-department"), false);

  if (user) {
    title.textContent = `編輯 #${user.id}：${user.display_name}（${user.username}）`;
    pwHint.textContent = "(留空 = 不修改)";
    form.elements.id.value = user.id;
    form.elements.username.value = user.username || "";
    form.elements.display_name.value = user.display_name || "";
    form.elements.password.value = "";
    form.elements.role.value = user.role || "student";
    form.elements.status.value = user.status || "active";
    form.elements.department.value = user.department || "";
    form.elements.student_id.value = user.student_id || "";
    form.elements.year_enrolled.value = user.year_enrolled ?? "";
    form.elements.section.value = user.section || "";
    form.elements.email.value = user.email || "";
    form.elements.phone.value = user.phone || "";
    form.elements.note.value = user.note || "";
    if (user.department_id) $("#users-form-department").value = user.department_id;
    toggleStudentsOnly(user.role);
    updateEmailPolicy(user.role, user.student_id);
  } else {
    title.textContent = "新增人員";
    pwHint.textContent = "(新增必填)";
    form.elements.id.value = "";
    form.elements.role.value = "student";
    form.elements.status.value = "active";
    form.elements.section.value = "";
    toggleStudentsOnly("student");
    updateEmailPolicy("student", "");
  }

  updateClassPreview();
  drawer.setAttribute("aria-hidden", "false");
  drawer.classList.add("drawer-open");
  setTimeout(() => form.elements.display_name.focus(), 50);
}

function updateEmailPolicy(role, studentId) {
  const emailEl = $("#users-form").elements.email;
  if (role === "student" && studentId) {
    emailEl.placeholder = `s${studentId}@nqu.edu.tw`;
  } else {
    emailEl.placeholder = "username@nqu.edu.tw";
  }
}

function updateClassPreview() {
  const form = $("#users-form");
  if (!form) return;
  const role = form.elements.role?.value;
  const preview = $("#users-class-preview");
  if (!preview) return;
  if (role !== "student") {
    preview.textContent = "";
    return;
  }
  const deptSel = $("#users-form-department");
  const deptOpt = deptSel?.selectedOptions[0];
  const deptName = deptOpt?.textContent || "";  // e.g. "CS — 資訊工程學系"
  const deptLong = deptName.split("—")[1]?.trim() || "";
  const year = parseInt(form.elements.year_enrolled?.value, 10);
  const section = form.elements.section?.value || "";

  // Strip "學系" suffix → "資工", keep "處" as-is.
  const prefix = deptLong.replace(/學系$/, "").replace(/系$/, "") || deptLong;

  const cnDigits = ["一", "二", "三", "四", "五", "六", "七", "八"];
  if (year && section) {
    const grade = (window.__nkuAcademicYear || 115) - year + 1;
    if (grade >= 1 && grade <= cnDigits.length) {
      preview.textContent = `即將顯示為：${prefix}${cnDigits[grade - 1]}${section}`;
      return;
    }
  }
  preview.textContent = "";
}

window.__nkuAcademicYear = window.__nkuAcademicYear || 115;

function closeDrawer() {
  const drawer = $("#users-drawer");
  drawer.classList.remove("drawer-open");
  drawer.setAttribute("aria-hidden", "true");
}

function showImportResult(data) {
  const modal = $("#import-result-modal");
  $("#import-result-summary").textContent =
    `總共 ${data.total} 列：建立 ${data.created}、略過 ${data.skipped}、錯誤 ${data.errors}。`;
  $("#import-stat-created").textContent = `建立 ${data.created}`;
  $("#import-stat-skipped").textContent = `略過 ${data.skipped}`;
  $("#import-stat-errors").textContent = `錯誤 ${data.errors}`;

  const list = $("#import-result-list");
  if (!data.results || data.results.length === 0) {
    list.innerHTML = `<p class="muted">沒有可匯入的資料列。</p>`;
  } else {
    list.innerHTML = `
      <table class="data-table import-result-table">
        <thead><tr><th>列</th><th>帳號</th><th>狀態</th><th>訊息</th></tr></thead>
        <tbody>${data.results.map((r) => `
          <tr class="import-row-${r.status}">
            <td>${r.row}</td>
            <td><code>${escape(r.username || "")}</code></td>
            <td>${statusLabel(r.status)}</td>
            <td>${escape(r.error || "")}</td>
          </tr>
        `).join("")}</tbody>
      </table>
    `;
  }
  if (typeof modal.showModal === "function") modal.showModal();
  else modal.setAttribute("open", "");
}

function statusLabel(s) {
  if (s === "created") return '<span class="badge badge-success">建立</span>';
  if (s === "skipped") return '<span class="badge badge-warning">略過</span>';
  if (s === "error") return '<span class="badge badge-role-admin">錯誤</span>';
  return escape(s);
}

export async function initAdminUsers() {
  // Load departments once for the filter dropdown and drawer select.
  try {
    state.departments = await fetchDepartments();
    populateDepartmentSelect($("#users-filter-department"), true);
  } catch (err) {
    showError("載入系所失敗：" + err.message);
  }

  await loadAndRender();

  $("#users-refresh").addEventListener("click", () => { state.page = 1; loadAndRender(); });
  $("#users-new").addEventListener("click", () => openDrawer(null));

  let searchTimer = null;
  $("#users-search").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.search = e.target.value;
      state.page = 1;
      loadAndRender();
    }, 250);
  });
  $("#users-filter-role").addEventListener("change", (e) => {
    state.role = e.target.value;
    state.page = 1;
    loadAndRender();
  });
  $("#users-filter-status").addEventListener("change", (e) => {
    state.status = e.target.value;
    state.page = 1;
    loadAndRender();
  });
  $("#users-filter-department").addEventListener("change", (e) => {
    state.department_id = e.target.value;
    state.page = 1;
    loadAndRender();
  });

  $("#users-prev").addEventListener("click", () => {
    if (state.page > 1) { state.page--; loadAndRender(); }
  });
  $("#users-next").addEventListener("click", () => {
    if (state.page < state.pages) { state.page++; loadAndRender(); }
  });

  // ---------- Bulk import / export ----------

  $("#users-download-template").addEventListener("click", () => {
    window.location.href = "/api/admin/users/template.csv";
  });

  $("#users-export").addEventListener("click", () => {
    const params = new URLSearchParams();
    if (state.role) params.set("role", state.role);
    if (state.status) params.set("status", state.status);
    if (state.department_id) params.set("department_id", state.department_id);
    const qs = params.toString();
    window.location.href = "/api/admin/users/export.csv" + (qs ? "?" + qs : "");
  });

  $("#users-import-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    showError("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("/api/admin/users/import", {
        method: "POST",
        body: fd,
        credentials: "same-origin",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        showError(data.error || `HTTP ${res.status}`);
        return;
      }
      showImportResult(data);
      loadAndRender();
    } catch (err) {
      showError("匯入失敗：" + err.message);
    } finally {
      e.target.value = "";  // allow re-upload of same file
    }
  });

  // Toggle students-only section when role changes
  $("#users-form").elements.role.addEventListener("change", (e) => {
    toggleStudentsOnly(e.target.value);
    const sid = $("#users-form").elements.student_id.value;
    updateEmailPolicy(e.target.value, sid);
    updateClassPreview();
  });
  $("#users-form").elements.student_id.addEventListener("input", (e) => {
    const role = $("#users-form").elements.role.value;
    updateEmailPolicy(role, e.target.value.trim());
  });
  // Live preview of the computed class name
  const form = $("#users-form");
  ["year_enrolled", "section"].forEach((name) => {
    form.elements[name].addEventListener("input", updateClassPreview);
    form.elements[name].addEventListener("change", updateClassPreview);
  });
  form.elements.department_id.addEventListener("change", updateClassPreview);
  // Fetch academic year from server once on init.
  fetch("/api/config")
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {
      if (data && data.academic_year) {
        window.__nkuAcademicYear = data.academic_year;
        updateClassPreview();
      }
    })
    .catch(() => {});

  $("#users-tbody").addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-action]");
    if (!btn) return;
    const tr = btn.closest("tr");
    const id = Number(tr.dataset.id);
    const username = tr.children[0].textContent.trim();
    const action = btn.dataset.action;

    if (action === "edit") {
      try {
        const res = await fetch(`/api/admin/users/${id}`, { credentials: "same-origin" });
        const data = await res.json();
        openDrawer(data.user);
      } catch (err) {
        showError("載入使用者失敗：" + err.message);
      }
      return;
    }

    if (action === "delete") {
      if (!confirm(`確定刪除 ${username}？（無法復原）`)) return;
      try {
        const res = await fetch(`/api/admin/users/${id}`, {
          method: "DELETE",
          credentials: "same-origin",
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { showError(data.error || `HTTP ${res.status}`); return; }
        loadAndRender();
      } catch (err) {
        showError("刪除失敗：" + err.message);
      }
      return;
    }

    if (action === "reset-pw") {
      state.resetTargetId = id;
      const modal = $("#reset-pw-modal");
      $("#reset-pw-username").textContent = username;
      const errBox = modal.querySelector("[data-role='reset-error']");
      if (errBox) { errBox.textContent = ""; errBox.hidden = true; }
      modal.querySelector("input[name=new_password]").value = "";
      if (typeof modal.showModal === "function") modal.showModal();
      else modal.setAttribute("open", "");
    }
  });

  document.querySelectorAll("#users-drawer [data-action='close']").forEach((el) => {
    el.addEventListener("click", closeDrawer);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeDrawer();
      const modal = $("#reset-pw-modal");
      if (modal.open) modal.close();
    }
  });

  $("#users-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    const errBox = form.querySelector("[data-role='form-error']");
    if (errBox) { errBox.textContent = ""; errBox.hidden = true; }

    const fd = new FormData(form);
    const id = fd.get("id");
    const payload = {
      username: (fd.get("username") || "").toString().trim(),
      display_name: (fd.get("display_name") || "").toString().trim(),
      role: (fd.get("role") || "").toString(),
      status: (fd.get("status") || "active").toString(),
      department: (fd.get("department") || "").toString().trim(),
      student_id: (fd.get("student_id") || "").toString().trim(),
      year_enrolled: fd.get("year_enrolled") ? Number(fd.get("year_enrolled")) : null,
      class_name: (fd.get("class_name") || "").toString().trim(),
      email: (fd.get("email") || "").toString().trim(),
      phone: (fd.get("phone") || "").toString().trim(),
      note: (fd.get("note") || "").toString().trim(),
      department_id: fd.get("department_id") ? Number(fd.get("department_id")) : null,
    };
    const pw = (fd.get("password") || "").toString();
    if (pw) payload.password = pw;
    else if (!id) payload.password = "placeholder";  // will be caught by validation

    const url = id ? `/api/admin/users/${id}` : "/api/admin/users";
    const method = id ? "PUT" : "POST";

    try {
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (errBox) { errBox.textContent = data.error || `HTTP ${res.status}`; errBox.hidden = false; }
        return;
      }
      closeDrawer();
      loadAndRender();
    } catch (err) {
      if (errBox) { errBox.textContent = "儲存失敗：" + err.message; errBox.hidden = false; }
    }
  });

  const resetModal = $("#reset-pw-modal");
  resetModal.addEventListener("close", () => { state.resetTargetId = null; });
  $("#reset-pw-submit").addEventListener("click", async (e) => {
    e.preventDefault();
    if (!state.resetTargetId) return;
    const errBox = resetModal.querySelector("[data-role='reset-error']");
    const fd = new FormData(resetModal.querySelector("form"));
    try {
      const res = await fetch(`/api/admin/users/${state.resetTargetId}/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ new_password: fd.get("new_password") }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (errBox) { errBox.textContent = data.error || `HTTP ${res.status}`; errBox.hidden = false; }
        return;
      }
      resetModal.close("confirm");
    } catch (err) {
      if (errBox) { errBox.textContent = "重設失敗：" + err.message; errBox.hidden = false; }
    }
  });
}
