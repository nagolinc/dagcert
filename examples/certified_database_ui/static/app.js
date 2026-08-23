"use strict";

const state = {
  page: 1,
  pageSize: 3,
  sort: "title",
  direction: "asc",
  loadVersion: 0,
};

window.__dagcertEvents = [];

function recordTiming(task, caseName, started, metadata = {}) {
  window.__dagcertEvents.push({
    task,
    case: caseName,
    value_ms: performance.now() - started,
    metadata,
  });
}

function showFeedback(message, action) {
  const started = performance.now();
  const status = document.querySelector("#action-status");
  status.textContent = message;
  status.dataset.action = action;
  recordTiming("ui.feedback", "visible", started, {action});
}

function renderRows(result) {
  const started = performance.now();
  const body = document.querySelector("#item-rows");
  body.replaceChildren();
  for (const item of result.items) {
    const row = document.createElement("tr");
    row.dataset.itemRow = "";
    row.dataset.rowKey = String(item.id);

    const title = document.createElement("td");
    title.dataset.field = "title";
    title.textContent = item.title;
    row.append(title);

    const category = document.createElement("td");
    category.dataset.field = "category";
    category.textContent = item.category;
    row.append(category);

    const action = document.createElement("td");
    const remove = document.createElement("button");
    remove.type = "button";
    remove.dataset.deleteId = String(item.id);
    remove.textContent = `Delete ${item.title}`;
    remove.addEventListener("click", () => removeItem(item.id, row));
    action.append(remove);
    row.append(action);
    body.append(row);
  }

  document.querySelector("#empty-state").hidden = result.items.length !== 0;
  document.querySelector("#result-summary").textContent = `${result.total} total items`;
  document.querySelector("#page-label").textContent = `Page ${result.page}`;
  document.querySelector("#previous-page").disabled = !result.has_previous;
  document.querySelector("#next-page").disabled = !result.has_next;
  state.loadVersion += 1;
  document.body.dataset.loadVersion = String(state.loadVersion);
  recordTiming("ui.render", "visible", started, {
    page: result.page,
    sort: result.sort,
    direction: result.direction,
    count: result.items.length,
  });
}

async function loadRows() {
  const query = new URLSearchParams({
    page: String(state.page),
    page_size: String(state.pageSize),
    sort: state.sort,
    direction: state.direction,
  });
  const response = await fetch(`/api/items?${query}`);
  if (!response.ok) {
    throw new Error(`list failed: ${response.status}`);
  }
  const result = await response.json();
  renderRows(result);
  return result;
}

async function addItem(event) {
  event.preventDefault();
  const form = event.currentTarget;
  showFeedback("Saving item...", "insert");
  try {
    const response = await fetch("/api/items", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        title: form.elements.title.value,
        category: form.elements.category.value,
      }),
    });
    if (!response.ok) {
      showFeedback("Insert failed", "insert-error");
      return;
    }
    form.reset();
    showFeedback("Item saved", "insert-complete");
    await loadRows();
  } catch (error) {
    showFeedback("Insert failed", "insert-error");
  }
}

async function removeItem(identifier, row) {
  showFeedback("Deleting item...", "delete");
  row.dataset.pending = "delete";
  try {
    const response = await fetch(`/api/items/${identifier}`, {method: "DELETE"});
    if (!response.ok) {
      row.removeAttribute("data-pending");
      showFeedback("Delete failed", "delete-error");
      return;
    }
    showFeedback("Item deleted", "delete-complete");
    const result = await loadRows();
    if (result.items.length === 0 && state.page > 1) {
      state.page -= 1;
      await loadRows();
    }
  } catch (error) {
    row.removeAttribute("data-pending");
    showFeedback("Delete failed", "delete-error");
  }
}

document.querySelector("#add-form").addEventListener("submit", addItem);
document.querySelector("#sort-field").addEventListener("change", async (event) => {
  state.sort = event.currentTarget.value;
  state.page = 1;
  await loadRows();
});
document.querySelector("#sort-direction").addEventListener("click", async (event) => {
  state.direction = state.direction === "asc" ? "desc" : "asc";
  event.currentTarget.dataset.direction = state.direction;
  event.currentTarget.textContent = state.direction === "asc" ? "Ascending" : "Descending";
  state.page = 1;
  await loadRows();
});
document.querySelector("#previous-page").addEventListener("click", async () => {
  state.page -= 1;
  await loadRows();
});
document.querySelector("#next-page").addEventListener("click", async () => {
  state.page += 1;
  await loadRows();
});

loadRows().catch((error) => showFeedback(error.message, "load-error"));
