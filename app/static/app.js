function setBusy(form, busy) {
  form.querySelectorAll("button, input[type='submit']").forEach((control) => {
    control.disabled = busy;
  });
  form.setAttribute("aria-busy", String(busy));
}

function showNotification(message, type = "error") {
  let notice = document.querySelector(".app-notification");
  if (!notice) {
    notice = document.createElement("div");
    notice.className = "app-notification";
    notice.setAttribute("role", "status");
    document.body.append(notice);
  }
  notice.dataset.type = type;
  notice.textContent = message;
}

function navigateToPreservedFilter(data) {
  if (data.redirect_url) {
    window.location.assign(data.redirect_url);
  }
}

async function submitImageAction(form) {
  setBusy(form, true);
  try {
    const response = await fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      headers: { "X-Requested-With": "fetch" },
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.message || "تعذر تنفيذ الإجراء");
    }
    showNotification(data.message, "success");
    navigateToPreservedFilter(data);
  } catch (error) {
    showNotification(error.message || "تعذر تنفيذ الإجراء", "error");
    setBusy(form, false);
  }
}

document.addEventListener("submit", (event) => {
  const form = event.target;

  if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
    event.preventDefault();
    return;
  }

  if (form.classList.contains("upload-form")) {
    setBusy(form, true);
    const loading = form.querySelector(".loading");
    if (loading) loading.hidden = false;
  }

  if (form.classList.contains("save-product")) {
    event.preventDefault();
    submitImageAction(form);
  }
});

document.addEventListener("DOMContentLoaded", () => {
  const input = document.querySelector("[data-direct-images-input]");
  if (!input) return;
  const summary = document.querySelector("[data-selected-images-summary]");
  const list = document.querySelector("[data-selected-images-list]");
  const maxBytes = 10 * 1024 * 1024;
  const formatSize = (bytes) => `${(bytes / (1024 * 1024)).toFixed(2)} MiB`;
  input.addEventListener("change", () => {
    const files = Array.from(input.files || []);
    list.textContent = "";
    summary.hidden = files.length === 0;
    summary.textContent = files.length ? `تم اختيار ${files.length} صورة.` : "";
    files.forEach((file) => {
      const item = document.createElement("li");
      item.textContent = `${file.name} — ${formatSize(file.size)}`;
      if (file.size > maxBytes) {
        item.className = "upload-warning";
        item.textContent += " — تتجاوز الحد المسموح وهو 10 ميغابايت.";
      }
      list.append(item);
    });
  });
});
