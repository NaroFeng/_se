import { $ } from "../core/dom.js";
import { login } from "../core/api.js";

function init() {
  const form = $("#login-form");
  if (!form) return;
  const errorBox = form.querySelector("[data-role='error']");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (errorBox) errorBox.hidden = true;
    const fd = new FormData(form);
    try {
      // Send identifier as-is; backend detects email vs username.
      await login(fd.get("username").toString().trim(), fd.get("password").toString());
      window.location.href = "/";
    } catch (err) {
      if (errorBox) {
        errorBox.textContent = err.message || "登入失敗";
        errorBox.hidden = false;
      }
    }
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
