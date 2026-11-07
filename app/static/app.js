const state = { csrf: "", categories: [], expenses: [] };
const money = new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 2 });
const fullDate = new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
const currentPeriod = new Intl.DateTimeFormat("en-CA", { year: "numeric", month: "2-digit" }).format(new Date()).slice(0, 7);

document.querySelectorAll("input[type='month']").forEach((input) => { input.value = currentPeriod; });

async function api(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  if (state.csrf && options.method && options.method !== "GET") headers["X-CSRF-Token"] = state.csrf;
  const response = await fetch(url, { ...options, headers });
  if (response.status === 401) {
    window.location.assign("/login");
    throw new Error("Сессия закончилась");
  }
  if (!response.ok) {
    let message = "Не удалось выполнить действие";
    try { message = (await response.json()).detail || message; } catch (_) { /* no body */ }
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function showToast(message) {
  const toast = document.querySelector("#toast");
  toast.textContent = message;
  toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => { toast.hidden = true; }, 2800);
}

function showScreen(name) {
  document.querySelectorAll(".screen").forEach((screen) => screen.classList.toggle("active", screen.id === `screen-${name}`));
  document.querySelectorAll("[data-screen]").forEach((link) => link.classList.toggle("active", link.dataset.screen === name));
  if (window.location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
  if (name === "overview") loadOverview();
  if (name === "history") loadHistory();
  if (name === "settings") loadSettings();
}

document.querySelectorAll("[data-screen]").forEach((link) => link.addEventListener("click", (event) => {
  event.preventDefault();
  showScreen(link.dataset.screen);
}));
document.querySelectorAll("[data-go]").forEach((link) => link.addEventListener("click", (event) => {
  event.preventDefault();
  showScreen(link.dataset.go);
}));

function planRow(item) {
  const row = el("div", "plan-row");
  row.append(el("div", "plan-name", item.name));
  const track = el("div", "plan-track");
  const fill = el("div", "plan-fill");
  fill.style.width = `${Math.min(item.ratio * 100, 100)}%`;
  track.append(fill);
  row.append(track);
  const values = el("div", `plan-values num${item.remaining < 0 ? " over" : ""}`);
  values.append(el("strong", "", money.format(Number(item.remaining))));
  values.append(el("small", "", `из ${money.format(Number(item.limit))}`));
  row.append(values);
  return row;
}

function recentRow(item) {
  const row = el("div", "recent-row");
  const copy = el("div");
  copy.append(el("p", "", item.category_name));
  copy.append(el("small", "", `${item.person} · ${fullDate.format(new Date(item.spent_at))}`));
  row.append(copy, el("div", "recent-amount num", money.format(Number(item.amount))));
  return row;
}

async function loadOverview() {
  const period = document.querySelector("#overview-period").value;
  try {
    const data = await api(`/web/api/overview?period=${encodeURIComponent(period)}`);
    document.querySelector("#remaining-value").textContent = money.format(Number(data.remaining));
    document.querySelector("#limit-value").textContent = money.format(Number(data.total_limit));
    document.querySelector("#spent-value").textContent = money.format(Number(data.total_spent));
    const remaining = Number(data.remaining);
    document.querySelector("#overview-finding").textContent = remaining < 0 ? `Лимит превышен на ${money.format(Math.abs(remaining))}` : `До конца месяца доступно ${money.format(remaining)}`;
    const plan = document.querySelector("#category-plan-list");
    plan.classList.remove("loading-block");
    plan.replaceChildren(...data.categories.map(planRow));
    if (!data.categories.length) plan.append(el("div", "empty-state", "На этот месяц лимиты ещё не заданы."));
    const recent = document.querySelector("#recent-list");
    recent.classList.remove("loading-block");
    recent.replaceChildren(...data.recent.map(recentRow));
    if (!data.recent.length) recent.append(el("div", "empty-state", "За этот месяц расходов нет."));
  } catch (error) { showToast(error.message); }
}

async function loadCategories(period) {
  const data = await api(`/web/api/categories?period=${encodeURIComponent(period)}`);
  state.categories = data.items;
  return data.items;
}

function fillCategorySelect(select, includeAll = false) {
  const nodes = [];
  if (includeAll) {
    const option = el("option", "", "Все категории");
    option.value = "";
    nodes.push(option);
  }
  state.categories.filter((item) => item.is_active).forEach((item) => {
    const option = el("option", "", item.name);
    option.value = String(item.id);
    nodes.push(option);
  });
  select.replaceChildren(...nodes);
}

function toLocalInput(iso) {
  const date = new Date(iso);
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function expenseRow(item) {
  const row = el("tr");
  row.append(el("td", "", fullDate.format(new Date(item.spent_at))));
  row.append(el("td", "", item.category_name));
  row.append(el("td", "", item.person));
  row.append(el("td", "num", money.format(Number(item.amount))));
  const actions = el("td");
  const button = el("button", "row-action");
  button.type = "button";
  button.setAttribute("aria-label", `Изменить трату ${money.format(Number(item.amount))}`);
  const image = document.createElement("img");
  image.src = "/static/icons/pencil.svg";
  image.alt = "";
  button.append(image);
  button.addEventListener("click", () => openEdit(item));
  actions.append(button);
  row.append(actions);
  return row;
}

async function loadHistory() {
  const period = document.querySelector("#history-period").value;
  try {
    const previousCategory = document.querySelector("#history-category").value;
    await loadCategories(period);
    fillCategorySelect(document.querySelector("#history-category"), true);
    document.querySelector("#history-category").value = previousCategory;
    const category = document.querySelector("#history-category").value;
    const suffix = category ? `&category_id=${encodeURIComponent(category)}` : "";
    const data = await api(`/web/api/expenses?period=${encodeURIComponent(period)}${suffix}`);
    state.expenses = data.items;
    document.querySelector("#history-summary").textContent = `${data.count} ${plural(data.count, "трата", "траты", "трат")} · ${money.format(Number(data.total))}`;
    document.querySelector("#expense-table").replaceChildren(...data.items.map(expenseRow));
    document.querySelector("#history-empty").hidden = data.items.length > 0;
  } catch (error) { showToast(error.message); }
}

function plural(number, one, few, many) {
  const mod10 = number % 10;
  const mod100 = number % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

function openEdit(item) {
  document.querySelector("#edit-id").value = item.id;
  document.querySelector("#edit-amount").value = item.amount;
  fillCategorySelect(document.querySelector("#edit-category"));
  document.querySelector("#edit-category").value = item.category_id;
  document.querySelector("#edit-date").value = toLocalInput(item.spent_at);
  document.querySelector("#edit-error").hidden = true;
  document.querySelector("#edit-dialog").showModal();
}

document.querySelector("#edit-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const id = document.querySelector("#edit-id").value;
  const error = document.querySelector("#edit-error");
  error.hidden = true;
  try {
    await api(`/web/api/expenses/${id}`, {
      method: "PATCH",
      body: JSON.stringify({
        amount: document.querySelector("#edit-amount").value,
        category_id: Number(document.querySelector("#edit-category").value),
        spent_at: new Date(document.querySelector("#edit-date").value).toISOString(),
      }),
    });
    document.querySelector("#edit-dialog").close();
    showToast("Трата обновлена");
    await loadHistory();
  } catch (requestError) {
    error.textContent = requestError.message;
    error.hidden = false;
  }
});

document.querySelector("#delete-expense").addEventListener("click", async () => {
  const item = state.expenses.find((expense) => String(expense.id) === document.querySelector("#edit-id").value);
  if (!item || !window.confirm(`Удалить трату ${money.format(Number(item.amount))} из истории?`)) return;
  try {
    await api(`/web/api/expenses/${item.id}`, { method: "DELETE" });
    document.querySelector("#edit-dialog").close();
    showToast("Трата удалена");
    await loadHistory();
  } catch (error) { showToast(error.message); }
});

document.querySelector("#close-edit").addEventListener("click", () => {
  document.querySelector("#edit-dialog").close();
});

function categorySetting(item, period) {
  const row = el("div", "category-setting");
  const nameLabel = el("label", "", "Название");
  const name = document.createElement("input");
  name.value = item.name;
  name.maxLength = 100;
  nameLabel.append(name);
  const limitLabel = el("label", "", "Лимит, ₽");
  const limit = document.createElement("input");
  limit.type = "number";
  limit.min = "0.01";
  limit.step = "0.01";
  limit.value = item.limit || "";
  limitLabel.append(limit);
  const active = el("label", "switch-line");
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = item.is_active;
  active.append(checkbox, document.createTextNode("Показывать на iPhone"));
  const save = el("button", "button save-category", "Сохранить");
  save.type = "button";
  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      await api(`/web/api/categories/${item.id}`, { method: "PATCH", body: JSON.stringify({ name: name.value, is_active: checkbox.checked }) });
      await api(`/web/api/budgets/${item.id}/${period}`, { method: "PUT", body: JSON.stringify({ limit: limit.value }) });
      showToast("Категория сохранена");
      await loadSettings();
    } catch (error) { showToast(error.message); } finally { save.disabled = false; }
  });
  row.append(nameLabel, limitLabel, active, save);
  return row;
}

async function loadSettings() {
  const period = document.querySelector("#settings-period").value;
  try {
    const categories = await loadCategories(period);
    const container = document.querySelector("#category-settings");
    container.replaceChildren(...categories.map((item) => categorySetting(item, period)));
    if (!categories.length) container.append(el("div", "empty-state", "Категорий пока нет."));
  } catch (error) { showToast(error.message); }
}

document.querySelector("#category-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    const created = await api("/web/api/categories", { method: "POST", body: JSON.stringify({ name: form.name.value, limit: form.limit.value }) });
    const period = document.querySelector("#settings-period").value;
    if (period !== currentPeriod) await api(`/web/api/budgets/${created.id}/${period}`, { method: "PUT", body: JSON.stringify({ limit: form.limit.value }) });
    form.reset();
    showToast("Категория добавлена");
    await loadSettings();
  } catch (error) { showToast(error.message); } finally { button.disabled = false; }
});

document.querySelector("#overview-period").addEventListener("change", loadOverview);
document.querySelector("#history-period").addEventListener("change", loadHistory);
document.querySelector("#history-category").addEventListener("change", loadHistory);
document.querySelector("#settings-period").addEventListener("change", loadSettings);
document.querySelector("#logout").addEventListener("click", async () => {
  try { await api("/auth/logout", { method: "POST" }); } finally { window.location.assign("/login"); }
});

(async function init() {
  try {
    const session = await api("/web/api/session");
    state.csrf = session.csrf_token;
    const requested = window.location.hash.slice(1);
    showScreen(["overview", "history", "settings"].includes(requested) ? requested : "overview");
  } catch (error) { showToast(error.message); }
})();
