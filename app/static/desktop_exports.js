(() => {
  let apiReady = false;
  let retryToken = null;
  let busy = false;
  const notifyBox = () => document.querySelector("[data-export-notification]") || document.querySelector("[data-order-notification]");
  const showExportNotification = (message, type = "info") => {
    const box = notifyBox();
    if (!box) return;
    box.textContent = message;
    box.dataset.type = type;
    box.hidden = false;
  };
  const saveExport = async (exportToken) => {
    if (!apiReady || !window.pywebview || !window.pywebview.api) {
      showExportNotification("واجهة الحفظ غير جاهزة بعد.", "error");
      return { ok: false };
    }
    return window.pywebview.api.save_generated_file(exportToken);
  };
  const handleExportResult = (result) => {
    if (result && result.ok) {
      retryToken = null;
      showExportNotification(`تم حفظ ملف Excel بنجاح. ${result.path || result.filename || ""}`, "success");
    } else if (result && result.cancelled) {
      showExportNotification("تم إلغاء الحفظ. يمكنك إعادة محاولة الحفظ.", "info");
    } else {
      showExportNotification("تعذر حفظ الملف.", "error");
    }
  };
  const setBusy = (button, value) => { busy = value; if (button) button.disabled = value; };
  const prepareOrderExport = async (orderId, csrfToken, button) => {
    if (busy) return;
    setBusy(button, true); showExportNotification("جارٍ تجهيز الملف...", "info");
    try {
      const body = new URLSearchParams(); body.set("csrf_token", csrfToken);
      const response = await fetch(`/orders/${encodeURIComponent(orderId)}/prepare-export`, { method: "POST", body });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error("prepare failed");
      retryToken = data.export_token;
      const result = await saveExport(data.export_token);
      handleExportResult(result);
      if (!result || (!result.cancelled && !result.ok)) retryToken = null;
    } catch (_) { showExportNotification("تعذر تجهيز الملف.", "error"); }
    finally { setBusy(button, false); }
  };
  const retryExport = async () => { if (retryToken) handleExportResult(await saveExport(retryToken)); };
  window.prepareOrderExport = prepareOrderExport;
  window.saveExport = saveExport;
  window.handleExportResult = handleExportResult;
  window.retryExport = retryExport;
  window.showExportNotification = showExportNotification;
  window.addEventListener("pywebviewready", () => { apiReady = true; });
  document.addEventListener("DOMContentLoaded", () => {
    const orderButton = document.querySelector("[data-desktop-export-order-id]");
    if (orderButton) {
      const run = () => prepareOrderExport(orderButton.dataset.desktopExportOrderId, orderButton.dataset.csrf, orderButton);
      orderButton.addEventListener("click", run);
      const script = document.querySelector('script[src*="desktop_exports.js"]');
      if (script && script.dataset.autoSave === "1") { history.replaceState(null, "", location.pathname); setTimeout(run, 250); }
    }
    const pricing = document.querySelector("[data-desktop-pricing-form]");
    if (pricing) pricing.addEventListener("submit", async (event) => {
      event.preventDefault(); if (busy) return;
      const button = pricing.querySelector('button[type="submit"]'); setBusy(button, true); showExportNotification("جارٍ تجهيز الملف...", "info");
      try { const response = await fetch(pricing.action, { method: "POST", body: new FormData(pricing) }); const data = await response.json(); if (!response.ok || !data.ok) throw new Error(); retryToken = data.export_token; const result = await saveExport(data.export_token); handleExportResult(result); if (result && result.ok) pricing.querySelector('input[type="file"]').value = ""; }
      catch (_) { showExportNotification("تعذر حفظ الملف.", "error"); }
      finally { setBusy(button, false); }
    });
  });
})();
