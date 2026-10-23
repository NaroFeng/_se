export async function request(method, url, body) {
  const opts = { method, headers: { "Content-Type": "application/json" }, credentials: "same-origin" };
  if (body !== undefined) opts.body = JSON.stringify(body);
  console.info("[api]", method, url);
  const res = await fetch(url, opts);
  console.info("[api]", method, url, "->", res.status);
  if (res.status === 401 && !url.includes("/api/auth/")) {
    // session expired for an authenticated endpoint → jump to login
    console.warn("[api] 401, jumping to /login");
    window.location.href = "/login";
  }
  let data = null;
  const text = await res.text();
  if (text) {
    try { data = JSON.parse(text); } catch { data = { raw: text }; }
  }
  if (!res.ok) {
    const err = new Error((data && (data.error || data.message)) || `HTTP ${res.status}`);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

export const api = {
  get: (url) => request("GET", url),
  post: (url, body) => request("POST", url, body || {}),
};

export async function getMenu() {
  const r = await api.get("/api/menu");
  return r.menu;
}

export async function listAnnouncements() {
  const r = await api.get("/api/announcements");
  return r.announcements;
}

export async function getAnnouncement(slug) {
  const r = await api.get(`/api/announcements/${encodeURIComponent(slug)}`);
  return r.announcement;
}

export async function login(username, password) {
  return api.post("/api/auth/login", { username, password });
}

export async function logout() {
  return api.post("/api/auth/logout", {});
}

export async function changePassword(oldPw, newPw) {
  return api.post("/api/auth/change-password", { old_password: oldPw, new_password: newPw });
}

export async function switchRole(role) {
  return api.post("/api/auth/switch-role", { role });
}

export async function getMe() {
  const r = await api.get("/api/auth/me");
  return r.user;
}