(() => {
  let busy = false;
  let timer;
  const box = () => document.querySelector("[data-backup-notification]");
  const notify = (message, type = "info", duration = 5000) => {
    const el = box(); if (!el) return;
    clearTimeout(timer); el.textContent = message; el.dataset.type = type; el.hidden = false;
    if (duration > 0) timer = setTimeout(() => { el.hidden = true; el.textContent = ""; el.removeAttribute("data-type"); }, duration);
  };
  const setBusy = (button, value) => { busy = value; if (button) button.disabled = value; };
  const post = async (url, values) => {
    const body = new URLSearchParams(values);
    const response = await fetch(url, { method: "POST", body });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.message || "failed");
    return data;
  };
  document.addEventListener("DOMContentLoaded", () => {
    const create = document.querySelector("[data-backup-create]");
    if (create) create.addEventListener("click", async () => {
      if (busy) return; setBusy(create, true); notify("جارٍ إنشاء النسخة الاحتياطية...", "info", 0);
      try {
        const data = await post("/backup/create", { csrf_token: create.dataset.csrf });
        if (!window.pywebview || !window.pywebview.api) throw new Error("واجهة الحفظ غير جاهزة.");
        const saved = await window.pywebview.api.save_backup_file(data.export_token);
        if (saved && saved.ok) notify(`تم حفظ النسخة الاحتياطية بنجاح. ${saved.path || saved.filename || ""}`, "success", 3000);
        else if (saved && saved.cancelled) notify("تم إلغاء الحفظ.", "info", 3000);
        else throw new Error((saved && saved.message) || "تعذر حفظ النسخة الاحتياطية.");
      } catch (e) { notify(e.message || "تعذر إنشاء النسخة الاحتياطية.", "error", 8000); }
      finally { setBusy(create, false); }
    });
    const restore = document.querySelector("[data-backup-restore]");
    if (restore) restore.addEventListener("click", async () => {
      if (busy) return;
      if (!confirm("هل تريد استعادة هذه النسخة؟ سيتم استبدال المنتجات والصور والطلبيات الحالية.")) return;
      setBusy(restore, true); notify("جارٍ اختيار النسخة والتحقق منها...", "info", 0);
      try {
        if (!window.pywebview || !window.pywebview.api) throw new Error("واجهة اختيار الملفات غير جاهزة.");
        const chosen = await window.pywebview.api.choose_backup_file();
        if (chosen && chosen.cancelled) { notify("تم إلغاء الاستعادة.", "info", 3000); return; }
        if (!chosen || !chosen.ok) throw new Error("تعذر اختيار النسخة الاحتياطية.");
        const data = await post("/backup/restore/stage", { csrf_token: restore.dataset.csrf, path: chosen.path });
        const counts = data.backup && data.backup.counts ? data.backup.counts : {};
        const summary = document.querySelector("[data-backup-summary]");
        if (summary) summary.textContent = `المنتجات: ${counts.products || 0}، الطلبيات: ${counts.orders || 0}، الصور: ${counts.image_files || 0}`;
        notify("تم التحقق من النسخة. سيعاد تشغيل طلبياتك لإكمال الاستعادة.", "success", 5000);
        if (window.pywebview.api.request_restart) await window.pywebview.api.request_restart();
      } catch (e) { notify(e.message || "تعذر استعادة النسخة الاحتياطية.", "error", 9000); }
      finally { setBusy(restore, false); }
    });
  });
})();
