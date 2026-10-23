import { $, $$ } from "../core/dom.js";
import { changePassword } from "../core/api.js";

export function initChangePasswordModal() {
  const modal = $("#change-password-modal");
  if (!modal) return;
  const errorBox = modal.querySelector("[data-role='error']");
  const form = modal.querySelector("form");
  const submit = $("#change-password-submit");

  function showError(msg) {
    if (!errorBox) return;
    errorBox.textContent = msg;
    errorBox.hidden = !msg;
  }

  modal.addEventListener("close", () => {
    if (form) form.reset();
    showError("");
  });

  if (submit) {
    submit.addEventListener("click", async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const oldPw = (fd.get("old_password") || "").toString();
      const newPw = (fd.get("new_password") || "").toString();
      const confirm = (fd.get("confirm_password") || "").toString();
      if (newPw !== confirm) {
        showError("新密碼與確認密碼不一致");
        return;
      }
      try {
        await changePassword(oldPw, newPw);
        modal.close("confirm");
      } catch (err) {
        showError(err.message || "修改失敗");
      }
    });
  }
}