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

function appendSharedProductToList(container, product, suffix = "") {
  const row = document.createElement("li");
  row.className = "shared-product-row";
  row.dataset.productId = product.id;
  const name = document.createElement("span");
  name.textContent = suffix ? `${product.name} — ${suffix}` : product.name;
  row.append(name);
  if (product.edit_url) {
    const link = document.createElement("a");
    link.className = "button secondary compact";
    link.href = product.edit_url;
    link.textContent = "تعديل";
    row.append(link);
  }
  container.append(row);
}

function showSharedImageProductPanel(card, product) {
  card.querySelectorAll("form.save-product").forEach((form) => { form.hidden = true; });
  const panel = document.createElement("div");
  panel.className = "shared-product-success";
  const title = document.createElement("p");
  title.textContent = "تم حفظ:";
  const first = document.createElement("strong");
  first.textContent = product.name;
  const heading = document.createElement("p");
  heading.textContent = "منتجات أخرى تستخدم الصورة:";
  const list = document.createElement("ul");
  list.className = "shared-products-list";
  const form = document.createElement("form");
  form.className = "shared-image-product-form";
  form.method = "post";
  form.action = `/products/${product.id}/create-with-same-image`;
  const csrf = card.querySelector("input[name='csrf_token']");
  const hidden = document.createElement("input");
  hidden.type = "hidden";
  hidden.name = "csrf_token";
  hidden.value = csrf ? csrf.value : "";
  const input = document.createElement("input");
  input.name = "name";
  input.required = true;
  input.maxLength = 300;
  input.placeholder = "اسم منتج آخر";
  const button = document.createElement("button");
  button.textContent = "إنشاء بنفس الصورة";
  const message = document.createElement("p");
  message.className = "shared-product-message";
  message.setAttribute("role", "status");
  form.append(hidden, input, button, message);
  const finish = document.createElement("button");
  finish.type = "button";
  finish.className = "button secondary compact finish-shared-products";
  finish.textContent = "إنهاء";
  panel.append(title, first, heading, list, form, finish);
  card.append(panel);
  input.focus();
}

async function submitSharedImageProduct(form) {
  if (form.dataset.busy === "true") return;
  form.dataset.busy = "true";
  setBusy(form, true);
  const message = form.querySelector(".shared-product-message");
  try {
    const response = await fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      headers: { "X-Requested-With": "fetch" },
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.message || "تعذر إنشاء المنتج");
    const list = form.closest(".shared-image-products-card, .shared-product-success").querySelector(".shared-products-list");
    appendSharedProductToList(list, data.product);
    form.reset();
    const input = form.querySelector("input[name='name']");
    if (input) input.focus();
    if (message) message.textContent = data.message;
    showNotification(data.message, "success");
  } catch (error) {
    if (message) message.textContent = error.message || "تعذر إنشاء المنتج";
    showNotification(error.message || "تعذر إنشاء المنتج", "error");
  } finally {
    form.dataset.busy = "false";
    setBusy(form, false);
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
    if (!response.ok || !data.ok) throw new Error(data.message || "تعذر تنفيذ الإجراء");
    showNotification(data.message, "success");
    const card = form.closest(".image-card");
    if (card && data.product) showSharedImageProductPanel(card, data.product);
    else if (data.redirect_url) window.location.href = data.redirect_url;
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
  if (form.classList.contains("shared-image-product-form")) {
    event.preventDefault();
    submitSharedImageProduct(form);
  }
});

document.addEventListener("click", (event) => {
  if (event.target.classList.contains("finish-shared-products")) {
    const card = event.target.closest(".image-card");
    if (card && ["unnamed", "duplicate"].includes(card.dataset.currentStatus || "")) card.remove();
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
