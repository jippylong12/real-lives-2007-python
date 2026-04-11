/* Real Lives 2007 — vanilla JS frontend
 * Single-file SPA. Talks to /api/* endpoints exposed by FastAPI.
 */

// ---------- Logging ----------
//
// All flow milestones go through log() so issues are visible in the
// browser DevTools console without having to scatter console.log calls
// every time something breaks. Errors print red with their stack.
const LOG_PREFIX = "%c[RL]%c";
const LOG_PREFIX_STYLE = "color:#bf6b3a;font-weight:600";
const LOG_RESET = "color:inherit;font-weight:normal";

function log(...args) {
  console.log(LOG_PREFIX, LOG_PREFIX_STYLE, LOG_RESET, ...args);
}
function logErr(label, err) {
  console.error(LOG_PREFIX, LOG_PREFIX_STYLE, "color:#c34a4a;font-weight:600", label, err);
  if (err && err.stack) console.error(err.stack);
}

// Catch any unhandled promise rejection (the most common cause of
// "I clicked a button and nothing happened" — an async function threw
// and the click handler swallowed the error).
window.addEventListener("unhandledrejection", (e) => {
  logErr("UNHANDLED PROMISE REJECTION:", e.reason);
});
window.addEventListener("error", (e) => {
  logErr("UNCAUGHT ERROR:", e.error || e.message);
});

const $ = (sel) => {
  const el = document.querySelector(sel);
  if (!el) log(`querySelector("${sel}") returned null`);
  return el;
};
const $$ = (sel) => document.querySelectorAll(sel);

// Variant that doesn't log when the element is intentionally optional.
const $opt = (sel) => document.querySelector(sel);

const state = {
  game: null,
  countries: [],
  investmentProducts: [],
  loanProducts: [],
};

// ---------- API ----------
async function api(path, opts = {}) {
  const method = opts.method || "GET";
  log(`→ ${method} ${path}`);
  let res;
  try {
    res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
  } catch (e) {
    logErr(`${method} ${path} failed (network)`, e);
    throw e;
  }
  if (!res.ok) {
    const text = await res.text();
    log(`← ${method} ${path} ${res.status}`, text);
    throw new Error(`${res.status}: ${text}`);
  }
  log(`← ${method} ${path} ${res.status}`);
  // Pulse the save indicator on every successful POST — every state
  // mutation auto-saves server-side, so this is honest feedback (#72).
  if (method === "POST") pulseSaveIndicator();
  return res.json();
}

// ---------- Save indicator (#72) ----------
let saveIndicatorTimer = null;
function pulseSaveIndicator() {
  const el = $opt("#save-indicator");
  if (!el) return;
  el.classList.add("pulsing");
  if (saveIndicatorTimer) clearTimeout(saveIndicatorTimer);
  saveIndicatorTimer = setTimeout(() => el.classList.remove("pulsing"), 700);
}

// =====================================================================
// Dialog + toast system
// =====================================================================
//
// Drop-in replacement for the browser's native alert() / confirm() that
// matches the editorial palette. Returns Promises so call sites read
// linearly:
//
//   await showAlert({ title: "Couldn't load", body: e.message });
//   if (!(await showConfirm({ title: "Quit job?", body: "..." }))) return;
//
// Toasts are non-blocking — fire-and-forget for lightweight feedback
// (purchase succeeded, slot loaded, etc.) so we don't pop a modal for
// every trivial event.

const DIALOG_ICONS = {
  default: "i",
  info:    "i",
  success: "\u2713",  // ✓
  danger:  "!",
  warning: "!",
};

let _dialogStack = [];  // tracks open dialogs for ESC handling

function _renderDialog({ title, body, kind, buttons, dismissible }) {
  const host = document.getElementById("rl-dialog-host");
  if (!host) {
    // Fail loud-but-soft: log and fall back to native so we never
    // silently swallow a critical message.
    console.error("[RL] dialog host missing");
    return null;
  }
  const backdrop = document.createElement("div");
  backdrop.className = "rl-dialog-backdrop";
  backdrop.setAttribute("role", "presentation");

  const card = document.createElement("div");
  card.className = "rl-dialog" + (kind && kind !== "default" ? ` ${kind}` : "");
  card.setAttribute("role", "dialog");
  card.setAttribute("aria-modal", "true");
  if (title) card.setAttribute("aria-labelledby", "rl-dialog-title");

  const iconGlyph = DIALOG_ICONS[kind || "default"] || DIALOG_ICONS.default;
  const iconHtml = `<div class="rl-dialog-icon" aria-hidden="true">${iconGlyph}</div>`;
  const titleHtml = title ? `<h3 id="rl-dialog-title" class="rl-dialog-title">${escapeHtml(title)}</h3>` : "";
  const bodyHtml  = body ? `<div class="rl-dialog-body">${escapeHtml(body)}</div>` : "";
  const actionsHtml = `<div class="rl-dialog-actions"></div>`;

  card.innerHTML = iconHtml + titleHtml + bodyHtml + actionsHtml;
  backdrop.appendChild(card);
  host.appendChild(backdrop);

  const actions = card.querySelector(".rl-dialog-actions");
  for (const b of buttons) {
    const btn = document.createElement("button");
    btn.className = "rl-dialog-btn" + (b.variant ? ` ${b.variant}` : "");
    btn.textContent = b.label;
    btn.addEventListener("click", () => b.onClick && b.onClick());
    actions.appendChild(btn);
  }

  // Click-outside dismiss for non-destructive dialogs.
  if (dismissible) {
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) {
        const cancelBtn = buttons.find((b) => b.role === "cancel") || buttons[buttons.length - 1];
        cancelBtn && cancelBtn.onClick && cancelBtn.onClick();
      }
    });
  }

  // Focus the primary button so Enter confirms immediately.
  const primaryBtn = actions.querySelector(".rl-dialog-btn.primary, .rl-dialog-btn.danger") ||
                     actions.querySelector(".rl-dialog-btn");
  if (primaryBtn) setTimeout(() => primaryBtn.focus(), 30);

  const handle = { backdrop, card, buttons, dismissible };
  _dialogStack.push(handle);
  return handle;
}

function _closeDialog(handle) {
  if (!handle || !handle.backdrop) return;
  handle.backdrop.classList.add("closing");
  setTimeout(() => {
    if (handle.backdrop && handle.backdrop.parentNode) {
      handle.backdrop.parentNode.removeChild(handle.backdrop);
    }
    _dialogStack = _dialogStack.filter((h) => h !== handle);
  }, 170);
}

// Global ESC handler — closes the topmost dialog if it's dismissible.
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || _dialogStack.length === 0) return;
  const top = _dialogStack[_dialogStack.length - 1];
  if (!top.dismissible) return;
  const cancelBtn = top.buttons.find((b) => b.role === "cancel") || top.buttons[top.buttons.length - 1];
  cancelBtn && cancelBtn.onClick && cancelBtn.onClick();
});

// #110: Spacebar shortcut — advance to next year.
document.addEventListener("keydown", (e) => {
  if (e.key !== " ") return;
  // Don't intercept when typing in an input, textarea, or select.
  const tag = document.activeElement?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  // Only fire on the game screen when alive, no modal open, no pending decision.
  if (!state.game) return;
  if (!state.game.character?.alive) return;
  if (state.game.pending_event) return;
  const gameScreen = document.getElementById("screen-game");
  if (!gameScreen || gameScreen.classList.contains("hidden")) return;
  // Check no modal is open (job board, emigration, decision, dialog stack).
  if (_dialogStack.length > 0) return;
  const modals = ["jobboard-modal", "emigration-modal", "decision-modal"];
  for (const id of modals) {
    const el = document.getElementById(id);
    if (el && !el.classList.contains("hidden")) return;
  }
  e.preventDefault();
  advanceYear();
});

function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Show a single-button informational dialog. Resolves when dismissed.
 * Replacement for `alert(msg)`.
 *
 *   await showAlert("Couldn't load that game: " + e.message);
 *   await showAlert({ title: "Saved", body: "Your progress is safe.", kind: "success" });
 */
function showAlert(opts) {
  if (typeof opts === "string") opts = { body: opts };
  const { title = "", body = "", kind = "info", confirmText = "OK" } = opts || {};
  return new Promise((resolve) => {
    let handle = null;
    const close = () => { _closeDialog(handle); resolve(); };
    handle = _renderDialog({
      title: title || _defaultTitleForKind(kind),
      body, kind, dismissible: true,
      buttons: [{ label: confirmText, variant: "primary", role: "confirm", onClick: close }],
    });
  });
}

/**
 * Show a two-button confirm dialog. Resolves true on confirm, false on
 * cancel (incl. ESC and click-outside if dismissible). Replacement for
 * `confirm(msg)`.
 *
 *   if (!(await showConfirm({ title: "Quit job?", body: "...", confirmText: "Quit" }))) return;
 *   await showConfirm({ ..., destructive: true })  // red confirm button
 */
function showConfirm(opts) {
  if (typeof opts === "string") opts = { body: opts };
  const {
    title = "Are you sure?",
    body = "",
    kind,
    confirmText = "Confirm",
    cancelText = "Cancel",
    destructive = false,
    dismissible = !destructive,
  } = opts || {};
  const dialogKind = kind || (destructive ? "danger" : "default");
  return new Promise((resolve) => {
    let handle = null;
    const finish = (val) => { _closeDialog(handle); resolve(val); };
    handle = _renderDialog({
      title, body, kind: dialogKind, dismissible,
      buttons: [
        { label: cancelText, variant: "", role: "cancel", onClick: () => finish(false) },
        {
          label: confirmText,
          variant: destructive ? "danger" : "primary",
          role: "confirm",
          onClick: () => finish(true),
        },
      ],
    });
  });
}

/**
 * Show a prompt dialog with a text input. Resolves with the trimmed
 * string on confirm, or null on cancel / ESC / click-outside.
 *
 *   const name = await showPrompt({ title: "New profile", placeholder: "Enter name" });
 *   if (!name) return; // cancelled
 */
function showPrompt(opts) {
  if (typeof opts === "string") opts = { title: opts };
  const {
    title = "Enter a value",
    body = "",
    placeholder = "",
    initialValue = "",
    confirmText = "OK",
    cancelText = "Cancel",
    maxLength = 40,
  } = opts || {};
  return new Promise((resolve) => {
    let handle = null;
    const finish = (val) => { _closeDialog(handle); resolve(val); };
    handle = _renderDialog({
      title, body, kind: "default", dismissible: true,
      buttons: [
        { label: cancelText, variant: "", role: "cancel", onClick: () => finish(null) },
        { label: confirmText, variant: "primary", role: "confirm", onClick: () => {
          const input = handle.card.querySelector(".rl-dialog-input");
          const val = input ? input.value.trim() : "";
          finish(val || null);
        }},
      ],
    });
    // Insert input field before the actions bar.
    const actions = handle.card.querySelector(".rl-dialog-actions");
    const input = document.createElement("input");
    input.type = "text";
    input.className = "rl-dialog-input";
    input.placeholder = placeholder;
    input.value = initialValue;
    input.maxLength = maxLength;
    handle.card.insertBefore(input, actions);
    // Enter key confirms.
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        const val = input.value.trim();
        finish(val || null);
      }
    });
    setTimeout(() => input.focus(), 30);
  });
}

function _defaultTitleForKind(kind) {
  switch (kind) {
    case "success": return "Done";
    case "danger":  return "Heads up";
    case "warning": return "Heads up";
    default:        return "Notice";
  }
}

/**
 * Fire-and-forget toast notification. Stacks top-right, auto-dismisses
 * after 4s. Use for lightweight confirmations that don't need to block
 * the player.
 *
 *   showToast("Saved your progress.");
 *   showToast("Bought a vacation for $2,000.", { kind: "success" });
 *   showToast("Couldn't reach the server.", { kind: "error", duration: 6000 });
 */
const TOAST_ICONS = { success: "\u2713", error: "!", info: "i" };

function showToast(message, opts = {}) {
  const host = document.getElementById("rl-toast-host");
  if (!host) { console.error("[RL] toast host missing"); return; }
  const { kind = "info", duration = 4000 } = opts;
  const toast = document.createElement("div");
  toast.className = `rl-toast ${kind}`;
  toast.setAttribute("role", "status");
  toast.innerHTML =
    `<span class="rl-toast-icon" aria-hidden="true">${TOAST_ICONS[kind] || TOAST_ICONS.info}</span>` +
    `<span class="rl-toast-msg">${escapeHtml(message)}</span>` +
    `<button class="rl-toast-close" aria-label="Dismiss">\u00d7</button>`;
  host.appendChild(toast);

  let timer = null;
  const close = () => {
    if (timer) { clearTimeout(timer); timer = null; }
    if (!toast.parentNode) return;
    toast.classList.add("closing");
    setTimeout(() => { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 200);
  };
  toast.querySelector(".rl-toast-close").addEventListener("click", close);
  if (duration > 0) timer = setTimeout(close, duration);
  return { close };
}

async function loadCountries() {
  state.countries = await api("/api/countries");
}

async function loadFinanceProducts() {
  const [inv, ln] = await Promise.all([
    api("/api/investments"),
    api("/api/loans"),
  ]);
  state.investmentProducts = inv;
  state.loanProducts = ln;
}

// Money-changing actions all funnel through this so the healthcare and
// spend panels stay in sync. Without this, taking a loan would update
// state.game but the healthcare panel's "not enough cash" data-blocked
// strings would still be baked in from the previous render — clicking
// a now-affordable Checkup button would still show the stale block.
function _afterMoneyChange() {
  renderGame();
  loadPurchases();
  loadHealthcare();
}

async function invest(productId, amount) {
  state.game = await api(`/api/game/${state.game.id}/invest`, {
    method: "POST",
    body: JSON.stringify({ product_id: productId, amount }),
  });
  _afterMoneyChange();
}

async function takeLoan(productId, amount) {
  state.game = await api(`/api/game/${state.game.id}/loan`, {
    method: "POST",
    body: JSON.stringify({ product_id: productId, amount }),
  });
  _afterMoneyChange();
}

async function sellInvestment(index) {
  state.game = await api(`/api/game/${state.game.id}/sell_investment`, {
    method: "POST",
    body: JSON.stringify({ index }),
  });
  _afterMoneyChange();
}

async function payLoan(index, amount) {
  state.game = await api(`/api/game/${state.game.id}/pay_loan`, {
    method: "POST",
    body: JSON.stringify({ index, amount }),
  });
  _afterMoneyChange();
}

// ---------- Spend (#66) ----------
const spendState = {
  category: "housing",
  purchases: [],
};

async function loadPurchases() {
  if (!state.game) return;
  try {
    spendState.purchases = await api(`/api/game/${state.game.id}/purchases`);
    renderSpendTab();
  } catch (e) {
    logErr("loadPurchases failed", e);
  }
}

function renderSpendTab() {
  const subsHost = $opt("#active-subscriptions");
  if (!subsHost) return;

  const c = state.game?.character;

  // Category tabs — derived from the purchase data so new categories
  // appear automatically (#112).
  const tabsHost = $opt("#purchase-categories");
  const CATEGORY_LABELS = {
    housing: "Housing", vehicles: "Vehicles", lifestyle: "Lifestyle",
    tech: "Tech", health: "Health & Wellness", subscription: "Subscriptions",
    education: "Education", charity: "Charity & Gifts",
  };
  const CATEGORY_ORDER = Object.keys(CATEGORY_LABELS);
  const seenCats = new Set(spendState.purchases.map((p) => p.category));
  const cats = CATEGORY_ORDER.filter((c) => seenCats.has(c));
  // Append any unknown categories at the end.
  for (const c of seenCats) { if (!cats.includes(c)) cats.push(c); }
  // If the active category isn't in the list, default to the first.
  if (!cats.includes(spendState.category)) spendState.category = cats[0] || "housing";
  tabsHost.innerHTML = "";
  for (const cat of cats) {
    const btn = document.createElement("button");
    btn.className = "purchase-tab" + (cat === spendState.category ? " active" : "");
    const icon = (typeof ICONS !== "undefined" && ICONS[cat]) || "";
    btn.innerHTML = (icon ? `<span class="tab-icon">${icon}</span>` : "") + escapeHtml(CATEGORY_LABELS[cat] || cat);
    btn.onclick = () => {
      spendState.category = cat;
      renderSpendTab();
    };
    tabsHost.appendChild(btn);
  }

  // Available + Owned split (#76)
  const inCategory = spendState.purchases.filter((p) => p.category === spendState.category);
  const available = inCategory.filter((p) => !p.owned && !p.subscribed);
  const owned = inCategory.filter((p) => p.owned || p.subscribed);

  // Active subscriptions block (always shown across categories)
  const subs = c?.subscriptions || {};
  if (Object.keys(subs).length === 0) {
    subsHost.innerHTML = "";
  } else {
    let html = "<h5 class='facts-heading'>Active subscriptions</h5>";
    for (const [key, sub] of Object.entries(subs)) {
      html += `<div class="sub-row">
        <span>${sub.name}</span>
        <span class="muted">${fmtMoney((sub.monthly_cost || 0) * 12)}/yr</span>
        <button class="btn xs" data-cancel-sub="${key}">Cancel</button>
      </div>`;
    }
    subsHost.innerHTML = html;
    subsHost.querySelectorAll("[data-cancel-sub]").forEach((b) => {
      b.onclick = () => cancelSubscription(b.dataset.cancelSub);
    });
  }

  // Available list
  const list = $opt("#purchase-list");
  list.innerHTML = "";

  if (available.length === 0 && owned.length === 0) {
    list.innerHTML = '<p class="muted">Nothing in this category.</p>';
    return;
  }

  for (const p of available) {
    list.appendChild(buildPurchaseRow(p, false));
  }

  // Owned/subscribed footer (#76) — only when there's something to show
  if (owned.length > 0) {
    const heading = document.createElement("h5");
    heading.className = "facts-heading";
    heading.textContent = "Owned & subscribed";
    list.appendChild(heading);
    for (const p of owned) {
      list.appendChild(buildPurchaseRow(p, true));
    }
  }

  list.querySelectorAll("[data-buy]").forEach((b) => {
    b.onclick = () => {
      const blocked = b.dataset.blocked;
      if (blocked) { showToast(blocked, { kind: "info" }); return; }
      buyPurchase(b.dataset.buy);
    };
  });
}

function buildPurchaseRow(p, isOwned) {
  const row = document.createElement("div");
  row.className = "purchase-row" + (isOwned ? " owned" : "") + (!p.eligible && !isOwned ? " disabled" : "");
  const costLabel = p.monthly_cost
    ? `${fmtMoney(p.monthly_cost)}/mo`
    : fmtMoney(p.cost);
  const ownedTag = p.owned ? '<span class="pr-owned">Owned</span>'
                  : p.subscribed ? '<span class="pr-owned">Subscribed</span>'
                  : '';

  // Effect chips (#77)
  let effectsHtml = "";
  if (p.effects && p.effects.length) {
    effectsHtml = '<div class="pr-effects">' +
      p.effects.map(e => `<span class="delta ${e.startsWith('-') ? 'down' : 'up'}">${e}</span>`).join('') +
      '</div>';
  }

  // Click-to-alert when blocked, like the healthcare buttons (#71)
  let actionHtml;
  if (isOwned) {
    actionHtml = '';  // no Buy button for owned items
  } else {
    const blockedReason = !p.eligible ? (p.reason || "not eligible") : "";
    actionHtml = `<button class="btn sm ${blockedReason ? 'blocked' : ''}" data-buy="${p.key}" data-blocked="${blockedReason}">Buy</button>`;
  }

  // Purchase type indicator: one-time, repeatable, or subscription
  let typeTag = "";
  if (p.monthly_cost) {
    typeTag = '<span class="pr-type sub" title="Recurring subscription"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8a5 5 0 0 1 9.5-1.5M13 8a5 5 0 0 1-9.5 1.5"/><path d="M12.5 3.5v3h-3M3.5 12.5v-3h3"/></svg></span>';
  } else if (!p.one_time) {
    typeTag = '<span class="pr-type repeat" title="Can buy again"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8a5 5 0 0 1 9.5-1.5M13 8a5 5 0 0 1-9.5 1.5"/><path d="M12.5 3.5v3h-3M3.5 12.5v-3h3"/></svg></span>';
  } else {
    typeTag = '<span class="pr-type once" title="One-time purchase"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3v10M5 6l3-3 3 3"/></svg></span>';
  }

  row.innerHTML = `
    <div class="pr-main">
      <div class="pr-name">${typeTag}${p.name} ${ownedTag}</div>
      <div class="pr-desc">${p.description}</div>
      ${effectsHtml}
    </div>
    <div class="pr-actions">
      <span class="pr-cost">${costLabel}</span>
      ${actionHtml}
    </div>`;
  return row;
}

async function buyPurchase(key) {
  log(`buyPurchase(${key})`);
  try {
    const res = await api(`/api/game/${state.game.id}/buy`, {
      method: "POST",
      body: JSON.stringify({ purchase_key: key }),
    });
    state.game = res.game;
    $opt("#spend-msg").textContent = res.message;
    $opt("#spend-msg").className = "good";
    await loadPurchases();
    renderGame();
  } catch (e) {
    logErr("buyPurchase failed", e);
    $opt("#spend-msg").textContent = e.message;
    $opt("#spend-msg").className = "form-msg";
  }
}

async function cancelSubscription(key) {
  log(`cancelSubscription(${key})`);
  try {
    const res = await api(`/api/game/${state.game.id}/cancel_subscription`, {
      method: "POST",
      body: JSON.stringify({ key }),
    });
    state.game = res.game;
    await loadPurchases();
    renderGame();
    if (res.message) showToast(res.message, { kind: "success" });
  } catch (e) {
    logErr("cancelSubscription failed", e);
    showToast(e.message, { kind: "error" });
  }
}

// ---------- Healthcare (#67) ----------
const healthState = {
  options: null,
};

async function loadHealthcare() {
  if (!state.game) return;
  try {
    healthState.options = await api(`/api/game/${state.game.id}/healthcare`);
    renderHealthcareActions();
  } catch (e) {
    logErr("loadHealthcare failed", e);
  }
}

function renderHealthcareActions() {
  const host = $opt("#healthcare-actions");
  if (!host || !healthState.options) return;
  const opts = healthState.options;
  const c = state.game?.character;
  if (!c) return;

  // Button rendering helper (#71): build a button that's *visually*
  // dimmed when blocked but still clickable, so the player gets an
  // alert with the blocked reason instead of silent nothing.
  function actionButton(id, label, cost, blockedReason) {
    const cantAfford = c.money < cost;
    const blocked = blockedReason || (cantAfford ? `not enough cash (need ${fmtMoney(cost)})` : null);
    const cls = blocked ? "btn xs blocked" : "btn xs";
    return `<button class="${cls}" id="${id}" data-blocked="${blocked || ""}">${label} ${fmtMoney(cost)}</button>`;
  }

  let html = "";

  if (opts.checkup) {
    html += actionButton(
      "btn-checkup",
      "Checkup",
      opts.checkup.cost,
      opts.checkup.eligible ? null : (opts.checkup.reason || "not eligible"),
    );
  }
  if (opts.major) {
    html += actionButton(
      "btn-major",
      "Major treatment",
      opts.major.cost,
      opts.major.eligible ? null : (opts.major.reason || "not eligible"),
    );
  }
  if (opts.diseases && opts.diseases.length) {
    for (const d of opts.diseases) {
      const verb = d.permanent ? "Manage" : "Cure";
      const blocked = c.money < d.cost ? `not enough cash (need ${fmtMoney(d.cost)})` : null;
      const cls = blocked ? "btn xs blocked" : "btn xs";
      html += `<button class="${cls}" data-treat-disease="${d.disease_key}" data-blocked="${blocked || ""}">${verb} ${d.name} ${fmtMoney(d.cost)}</button>`;
    }
  }

  host.innerHTML = html;

  // Wire clicks. Blocked buttons surface their reason as a toast,
  // live buttons call the action.
  function wireAction(id, action) {
    const btn = $opt("#" + id);
    if (!btn) return;
    btn.addEventListener("click", () => {
      const blocked = btn.dataset.blocked;
      if (blocked) { showToast(blocked, { kind: "info" }); return; }
      action();
    });
  }
  wireAction("btn-checkup", buyCheckup);
  wireAction("btn-major", buyMajorTreatment);
  host.querySelectorAll("[data-treat-disease]").forEach((b) => {
    b.onclick = () => {
      const blocked = b.dataset.blocked;
      if (blocked) { showToast(blocked, { kind: "info" }); return; }
      treatDisease(b.dataset.treatDisease);
    };
  });
}

async function buyCheckup() {
  log("buyCheckup");
  try {
    const res = await api(`/api/game/${state.game.id}/buy_checkup`, { method: "POST" });
    state.game = res.game;
    showToast(res.message, { kind: "success" });
    await loadHealthcare();
    renderGame();
  } catch (e) {
    logErr("buyCheckup failed", e);
    showToast(e.message, { kind: "error" });
  }
}

async function buyMajorTreatment() {
  log("buyMajorTreatment");
  try {
    const res = await api(`/api/game/${state.game.id}/buy_major_treatment`, { method: "POST" });
    state.game = res.game;
    showToast(res.message, { kind: "success" });
    await loadHealthcare();
    renderGame();
  } catch (e) {
    logErr("buyMajorTreatment failed", e);
    showToast(e.message, { kind: "error" });
  }
}

async function treatDisease(diseaseKey) {
  log(`treatDisease(${diseaseKey})`);
  try {
    const res = await api(`/api/game/${state.game.id}/treat_disease`, {
      method: "POST",
      body: JSON.stringify({ disease_key: diseaseKey }),
    });
    state.game = res.game;
    showToast(res.message, { kind: "success" });
    await loadHealthcare();
    renderGame();
  } catch (e) {
    logErr("treatDisease failed", e);
    showToast(e.message, { kind: "error" });
  }
}

async function quitJob() {
  const ok = await showConfirm({
    title: "Quit your current job?",
    body: "You'll need to find a new one — and there's no guarantee a better offer is waiting.",
    confirmText: "Quit job",
    cancelText: "Stay",
    destructive: true,
  });
  if (!ok) return;
  log("quitJob");
  try {
    state.game = await api(`/api/game/${state.game.id}/quit_job`, { method: "POST" });
    renderGame();
  } catch (e) {
    logErr("quitJob failed", e);
    showToast(`Could not quit job: ${e.message}`, { kind: "error" });
  }
}

async function dropOutOfSchool() {
  const ok = await showConfirm({
    title: "Drop out of school?",
    body: "You'll start looking for work right away. You can enroll in university later, but it will cost tuition.",
    confirmText: "Drop out",
    cancelText: "Stay in school",
    destructive: true,
  });
  if (!ok) return;
  log("dropOutOfSchool");
  try {
    state.game = await api(`/api/game/${state.game.id}/drop_out_of_school`, { method: "POST" });
    renderGame();
    loadPurchases();
    loadHealthcare();
  } catch (e) {
    logErr("dropOutOfSchool failed", e);
    showToast(`Could not drop out: ${e.message}`, { kind: "error" });
  }
}

// ---------- Profile management (#111) ----------
const _NEW_PROFILE_SENTINEL = "__new__";
let _profileListenerAttached = false;

async function loadProfileDropdown() {
  const select = $opt("#profile-select");
  if (!select) return;
  let players = [];
  try {
    players = await api("/api/players");
  } catch (e) {
    logErr("loadProfileDropdown failed", e);
  }
  const active = getActivePlayer();
  select.innerHTML = "";

  // Build options: existing profiles + "New Profile..."
  for (const name of players) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    if (name === active) opt.selected = true;
    select.appendChild(opt);
  }
  // If the active player isn't in the list yet (e.g., just created but
  // has no saved games yet), add it so they stay selected.
  if (active && !players.includes(active)) {
    const opt = document.createElement("option");
    opt.value = active;
    opt.textContent = active;
    opt.selected = true;
    select.insertBefore(opt, select.firstChild);
  }
  // "New Profile..." option
  const newOpt = document.createElement("option");
  newOpt.value = _NEW_PROFILE_SENTINEL;
  newOpt.textContent = "+ New Profile...";
  select.appendChild(newOpt);

  // If no active player and no existing profiles, prompt for creation.
  if (!active && players.length === 0) {
    select.value = _NEW_PROFILE_SENTINEL;
    await createNewProfile(select);
  }

  // Attach the change listener only once.
  if (!_profileListenerAttached) {
    _profileListenerAttached = true;
    select.addEventListener("change", async () => {
      if (select.value === _NEW_PROFILE_SENTINEL) {
        await createNewProfile(select);
        return;
      }
      setActivePlayer(select.value);
      await loadSlots();
      renderSlotGrid();
      showToast(`Playing as ${select.value}`, { kind: "info" });
    });
  }
}

async function createNewProfile(select) {
  const name = await showPrompt({
    title: "New profile",
    body: "Profiles separate your save slots and statistics.",
    placeholder: "Enter a name",
    confirmText: "Create",
  });
  if (!name) {
    // Cancelled — revert to previous selection.
    select.value = getActivePlayer() || (select.options.length > 1 ? select.options[0].value : "");
    return;
  }
  setActivePlayer(name);
  // Add the new profile to the dropdown if it's not already there.
  const exists = Array.from(select.options).some((o) => o.value === name);
  if (!exists) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    // Insert before the "New Profile..." option.
    select.insertBefore(opt, select.lastChild);
  }
  select.value = name;
  await loadSlots();
  renderSlotGrid();
  showToast(`Created profile: ${name}`, { kind: "success" });
}

async function renameProfile() {
  const current = getActivePlayer();
  if (!current) return;
  const newName = await showPrompt({
    title: "Rename profile",
    placeholder: "New name",
    initialValue: current,
    confirmText: "Rename",
  });
  if (!newName || newName === current) return;
  try {
    await api(`/api/players/${encodeURIComponent(current)}/rename`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_name: newName }),
    });
    setActivePlayer(newName);
    await loadProfileDropdown();
    await loadSlots();
    renderSlotGrid();
    showToast(`Renamed to "${newName}"`, { kind: "success" });
  } catch (e) {
    logErr("renameProfile failed", e);
    showToast(`Rename failed: ${e.message}`, { kind: "error" });
  }
}

async function deleteProfile() {
  const current = getActivePlayer();
  if (!current) return;
  const ok = await showConfirm({
    title: `Delete profile "${current}"?`,
    body: "This will permanently delete all save slots and game history for this profile. Statistics are kept.",
    destructive: true,
    confirmText: "Delete profile",
  });
  if (!ok) return;
  try {
    await api(`/api/players/${encodeURIComponent(current)}/delete`, { method: "POST" });
    // Fetch remaining profiles and auto-select the first one (or prompt
    // for a new profile if none remain). Without this, the dropdown
    // goes blank and the other profile's slots disappear.
    let remaining = [];
    try { remaining = await api("/api/players"); } catch {}
    const next = remaining.filter((n) => n !== current)[0] || "";
    setActivePlayer(next);
    await loadProfileDropdown();
    await loadSlots();
    renderSlotGrid();
    showToast(`Deleted profile "${current}"`, { kind: "success" });
  } catch (e) {
    logErr("deleteProfile failed", e);
    showToast(`Delete failed: ${e.message}`, { kind: "error" });
  }
}

// ---------- Late university enrollment (#107) ----------
async function enrollUniversity() {
  const c = state.game?.character;
  if (!c) return;
  const tuition = c.university_tuition || 0;
  const ok = await showConfirm({
    title: "Enroll in university?",
    body: `Tuition is ~${fmtMoney(tuition)}/yr (4 years). You can keep working while enrolled.`,
    confirmText: "Enroll",
    cancelText: "Not now",
  });
  if (!ok) return;
  log("enrollUniversity");
  try {
    const res = await api(`/api/game/${state.game.id}/enroll_university`, { method: "POST" });
    state.game = res.game;
    showToast(res.message, { kind: "info" });
    renderGame();
  } catch (e) {
    logErr("enrollUniversity failed", e);
    showToast(`Could not enroll: ${e.message}`, { kind: "error" });
  }
}

async function tryForChild() {
  const c = state.game?.character;
  if (!c) return;
  const ok = await showConfirm({
    title: "Try for a child?",
    body: "You and your spouse will try to have a child this year. Success isn't guaranteed and depends on age.",
    confirmText: "Try",
    cancelText: "Not now",
  });
  if (!ok) return;
  try {
    const res = await api(`/api/game/${state.game.id}/try_for_child`, { method: "POST" });
    state.game = res.game;
    const r = res.result;
    if (r.success) {
      showToast(r.message, { kind: "success", duration: 6000 });
    } else {
      showToast(r.message, { kind: "info", duration: 5000 });
    }
    renderGame();
  } catch (e) {
    logErr("tryForChild failed", e);
    showToast(e.message || "Couldn't try for a child.", { kind: "error" });
  }
}

// ---------- Save slots (#79) ----------
//
// 5 fixed save slots. The start screen shows one card per slot.
// Empty/dead slots open a country picker scoped to that slot. Alive
// slots load directly. State is fetched fresh from /api/slots whenever
// the start screen renders so the UI stays in sync with the server.
const slotState = {
  slots: [],          // last fetched /api/slots payload
  pendingSlot: null,  // slot the country picker is currently scoped to
};

// #85: active player name. Persists in localStorage so multi-player
// installs survive a refresh. Empty string = unscoped (legacy view).
function getActivePlayer() {
  try {
    return (localStorage.getItem("rl_active_player") || "").trim();
  } catch {
    return "";
  }
}
function setActivePlayer(name) {
  try {
    localStorage.setItem("rl_active_player", (name || "").trim());
  } catch {
    /* localStorage may be disabled — non-fatal */
  }
}
function playerQuery() {
  const p = getActivePlayer();
  return p ? `?player=${encodeURIComponent(p)}` : "";
}
function playerSuffix() {
  // For endpoints that already have a query string.
  const p = getActivePlayer();
  return p ? `&player=${encodeURIComponent(p)}` : "";
}

async function loadSlots() {
  try {
    slotState.slots = await api(`/api/slots${playerQuery()}`);
    log(`loaded ${slotState.slots.length} slots (player=${getActivePlayer() || "—"})`);
  } catch (e) {
    logErr("loadSlots failed", e);
    slotState.slots = [];
  }
}

function renderSlotGrid() {
  const host = $opt("#slot-grid");
  if (!host) return;
  host.innerHTML = "";
  for (const s of slotState.slots) {
    const card = document.createElement("button");
    card.className = `slot-card slot-${s.state}`;
    if (s.state === "empty") {
      card.innerHTML = `
        <div class="slot-num">Slot ${s.slot}</div>
        <div class="slot-empty-msg">Empty</div>
        <div class="slot-empty-cta">Click to start a new life</div>`;
      card.onclick = () => openCountryPickerForSlot(s.slot);
    } else if (s.state === "alive") {
      const flag = s.country_code
        ? `<img class="slot-flag" src="/flags/${s.country_code}.bmp" alt="">` : "";
      card.innerHTML = `
        <div class="slot-num">Slot ${s.slot}</div>
        ${flag}
        <div class="slot-name">${s.character_name}</div>
        <div class="slot-meta">${s.country_name || (s.country_code || "").toUpperCase()} · age ${s.age}</div>
        <div class="slot-cta">Continue</div>`;
      card.onclick = () => loadGameById(s.game_id);
    } else { // dead
      const flag = s.country_code
        ? `<img class="slot-flag" src="/flags/${s.country_code}.bmp" alt="">` : "";
      const cause = s.cause_of_death ? ` — ${s.cause_of_death}` : "";
      card.innerHTML = `
        <div class="slot-num">Slot ${s.slot}</div>
        ${flag}
        <div class="slot-name">${s.character_name}</div>
        <div class="slot-meta">${s.country_name || (s.country_code || "").toUpperCase()} · died at ${s.age}${cause}</div>
        <div class="slot-actions">
          <button class="btn xs" data-view="${s.game_id}">View life</button>
          <button class="btn xs primary" data-fresh="${s.slot}">Start new life</button>
        </div>`;
      // The whole card is also clickable to start a new life — easier on touch.
      card.onclick = (e) => {
        const t = e.target;
        if (t && t.dataset && t.dataset.view) {
          loadGameById(t.dataset.view);
          return;
        }
        openCountryPickerForSlot(s.slot);
      };
    }
    host.appendChild(card);
  }
}

function openCountryPickerForSlot(slot) {
  log(`openCountryPickerForSlot(${slot})`);
  slotState.pendingSlot = slot;
  $opt("#slot-picker-view").classList.add("hidden");
  $opt("#country-picker-view").classList.remove("hidden");
  const title = $opt("#country-picker-title");
  if (title) title.textContent = `Choose a country for slot ${slot}`;
  // Reset picker filters every time so old searches don't stick around.
  pickerState.search = "";
  pickerState.region = "All";
  const search = $opt("#picker-search");
  if (search) search.value = "";
  $$(".region-tab").forEach((t) => t.classList.toggle("active", t.dataset.region === "All"));
  renderCountryGrid();
}

function backToSlotPicker() {
  slotState.pendingSlot = null;
  $opt("#country-picker-view").classList.add("hidden");
  $opt("#slot-picker-view").classList.remove("hidden");
}

async function loadGameById(gameId) {
  log(`loadGameById(${gameId})`);
  try {
    state.game = await api(`/api/game/${gameId}`);
    // Reset stale UI from any previous render
    $opt("#event-list").innerHTML = '<p class="placeholder">Welcome back. Click "Live another year" to keep going.</p>';
    $opt("#timeline").innerHTML = "";
    $opt("#decision-modal")?.classList.add("hidden");
    showGameScreen();
    renderGame();
    loadPurchases();
    loadHealthcare();
  } catch (e) {
    logErr("loadGameById failed", e);
    showToast(`Could not load that game: ${e.message}`, { kind: "error" });
  }
}

// ---------- Job board (#54, #57, #58) ----------
const jobboardState = {
  category: "All",
  listings: [],
  show_all: false,  // false = hide long_shot + out_of_reach (#58)
};

async function openJobBoard() {
  log("openJobBoard");
  try {
    jobboardState.listings = await api(`/api/game/${state.game.id}/job_board`);
    log(`fetched ${jobboardState.listings.length} job listings`);
    jobboardState.category = "All";
    renderJobBoardTabs();
    renderJobBoardList();
    $("#jobboard-msg").textContent = "";
    $("#jobboard-modal").classList.remove("hidden");
  } catch (e) {
    logErr("openJobBoard failed", e);
    showToast(`Could not load the job board: ${e.message}`, { kind: "error" });
  }
}

function closeJobBoard() {
  $("#jobboard-modal").classList.add("hidden");
}

// ---------- Emigration (#49) ----------
const emigrationState = {
  options: [],
};

async function openEmigrationPicker() {
  log("openEmigrationPicker");
  try {
    emigrationState.options = await api(`/api/game/${state.game.id}/emigration_options`);
    log(`fetched ${emigrationState.options.length} emigration options`);
    renderEmigrationPicker();
    $("#emigration-modal").classList.remove("hidden");
  } catch (e) {
    logErr("openEmigrationPicker failed", e);
    showToast(`Couldn't load emigration options: ${e.message}`, { kind: "error" });
  }
}

function closeEmigrationPicker() {
  $("#emigration-modal").classList.add("hidden");
}

function renderEmigrationPicker() {
  const grid = $("#emigration-grid");
  grid.innerHTML = "";
  // Sort: eligible first, then alphabetical by name.
  const sorted = [...emigrationState.options].sort((a, b) => {
    if (a.eligible !== b.eligible) return a.eligible ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
  // Cost shown in the header — same for all targets so pull from any entry.
  const costStr = sorted.length ? fmtMoney(sorted[0].estimated_cost) : "—";
  $("#emigration-cost").textContent = `~${costStr} relocation cost`;
  for (const opt of sorted) {
    const tile = document.createElement("button");
    tile.className = `country-tile emigration-tile ${opt.eligible ? "eligible" : "blocked"}`;
    const routeText = opt.eligible
      ? opt.routes.map(r => r.replace(/_/g, " ")).join(" · ")
      : (opt.blocked_reason || "blocked");
    tile.innerHTML = `
      <img src="/flags/${opt.code}.bmp" alt="">
      <div class="et-name">${escapeHtml(opt.name)}</div>
      <div class="et-route muted">${escapeHtml(routeText)}</div>
    `;
    if (opt.eligible) {
      tile.onclick = () => confirmEmigrate(opt);
    } else {
      tile.disabled = true;
      tile.title = opt.blocked_reason || "blocked";
    }
    grid.appendChild(tile);
  }
}

async function confirmEmigrate(opt) {
  const ok = await showConfirm({
    title: `Move to ${opt.name}?`,
    body: `You'll move via a ${opt.routes[0].replace(/_/g, " ")} visa. Your job will be cleared and roughly ${fmtMoney(opt.estimated_cost)} of your family wealth goes to visa fees and relocation. Your spouse and children come with you.`,
    confirmText: "Move",
    cancelText: "Cancel",
    destructive: true,
  });
  if (!ok) return;
  log(`emigrate(${opt.code})`);
  try {
    const res = await api(`/api/game/${state.game.id}/emigrate`, {
      method: "POST",
      body: JSON.stringify({ country_code: opt.code }),
    });
    state.game = res.game;
    showToast(res.message, { kind: "success" });
    closeEmigrationPicker();
    renderGame();
    loadHealthcare();
    loadPurchases();
  } catch (e) {
    logErr("emigrate failed", e);
    showToast(`Couldn't emigrate: ${e.message}`, { kind: "error" });
  }
}

// Pseudo-category constant for the Self-employment tab. Distinct from
// the real job categories so renderJobBoardList knows to filter on
// is_freelance instead of an exact category match. (#83)
const SELF_EMPLOYED_TAB = "Self-employment";

function renderJobBoardTabs() {
  const tabs = $("#jobboard-tabs");
  // Tab order: All, Self-employment, then alphabetical real categories.
  const realCats = [...new Set(jobboardState.listings.map((l) => l.category).filter(Boolean))].sort();
  const cats = ["All", SELF_EMPLOYED_TAB, ...realCats];
  tabs.innerHTML = "";
  for (const c of cats) {
    const btn = document.createElement("button");
    btn.className = "region-tab" + (c === jobboardState.category ? " active" : "");
    btn.textContent = c;
    btn.onclick = () => {
      jobboardState.category = c;
      $$(".jobboard-tabs .region-tab").forEach((t) => t.classList.toggle("active", t.textContent === c));
      renderJobBoardList();
    };
    tabs.appendChild(btn);
  }
}

function renderJobBoardList() {
  const host = $("#jobboard-list");
  host.innerHTML = "";
  let listings = jobboardState.listings;
  if (jobboardState.category === SELF_EMPLOYED_TAB) {
    // Self-employment tab pulls every is_freelance listing across all
    // real categories. (#83)
    listings = listings.filter((l) => l.is_freelance);
  } else if (jobboardState.category !== "All") {
    listings = listings.filter((l) => l.category === jobboardState.category);
  }
  // Hide long shots and out-of-reach unless the player toggled them on (#58).
  if (!jobboardState.show_all) {
    listings = listings.filter((l) => l.status === "qualified" || l.status === "stretch");
  }
  // Sort: qualified > stretch > long_shot > out_of_reach, then salary desc.
  const statusOrder = { qualified: 0, stretch: 1, long_shot: 2, out_of_reach: 3 };
  listings = [...listings].sort((a, b) => {
    const so = statusOrder[a.status] - statusOrder[b.status];
    return so !== 0 ? so : b.expected_salary - a.expected_salary;
  });
  if (listings.length === 0) {
    if (!jobboardState.show_all) {
      host.innerHTML = '<p class="muted">No realistic options in this category yet — toggle <strong>Show long shots</strong> to see everything.</p>';
    } else {
      host.innerHTML = '<p class="muted">No jobs in this category.</p>';
    }
    return;
  }
  for (const l of listings) {
    const row = document.createElement("div");
    row.className = `jobboard-row status-${l.status}`;
    const chancePct = Math.round(l.accept_chance * 100);
    const missing = l.missing.length ? `<div class="jr-missing">${l.missing.join(" · ")}</div>` : "";
    const freelanceTag = l.is_freelance ? '<span class="jr-freelance">freelance · earnings depend on talent</span>' : "";
    row.innerHTML = `
      <div class="jr-main">
        <div class="jr-name">${l.name}${l.is_freelance ? " ⚡" : ""}</div>
        <div class="jr-meta">${l.category || "—"} · ${fmtMoney(l.expected_salary)}/yr</div>
        ${freelanceTag}
        ${missing}
      </div>
      <div class="jr-actions">
        <span class="jr-chance">${chancePct}%</span>
        <button class="btn sm" data-apply="${l.name.replace(/"/g, "&quot;")}">Apply</button>
      </div>`;
    host.appendChild(row);
  }
  host.querySelectorAll("[data-apply]").forEach((b) => {
    b.onclick = () => applyJob(b.dataset.apply);
  });
}

async function applyJob(jobName) {
  log(`applyJob(${jobName})`);
  try {
    const res = await api(`/api/game/${state.game.id}/apply_job`, {
      method: "POST",
      body: JSON.stringify({ job_name: jobName }),
    });
    state.game = res.game;
    $("#jobboard-msg").textContent = res.message;
    $("#jobboard-msg").className = res.accepted ? "good" : "muted";
    if (res.accepted) {
      // Refresh listings since the character's eligibility for everything changed.
      jobboardState.listings = await api(`/api/game/${state.game.id}/job_board`);
      renderJobBoardList();
      renderGame();
    }
  } catch (e) {
    logErr("applyJob failed", e);
    showToast(`Apply failed: ${e.message}`, { kind: "error" });
  }
}

async function requestRaise() {
  const ok = await showConfirm({
    title: "Ask for a raise?",
    body: "You could get one — or you could be let go. Approach with care.",
    confirmText: "Ask anyway",
    cancelText: "Not now",
  });
  if (!ok) return;
  log("requestRaise");
  try {
    const res = await api(`/api/game/${state.game.id}/request_raise`, { method: "POST" });
    state.game = res.game;
    log(`raise outcome: ${res.outcome} — ${res.message}`);
    showToast(res.message, { kind: res.outcome === "fired" ? "error" : "success" });
    renderGame();
  } catch (e) {
    logErr("requestRaise failed", e);
    showToast(`Could not request raise: ${e.message}`, { kind: "error" });
  }
}

async function requestPromotion() {
  const ok = await showConfirm({
    title: "Ask for a promotion?",
    body: "You could move up — or you could be let go. Don't ask unless you've earned it.",
    confirmText: "Ask anyway",
    cancelText: "Not now",
  });
  if (!ok) return;
  log("requestPromotion");
  try {
    const res = await api(`/api/game/${state.game.id}/request_promotion`, { method: "POST" });
    state.game = res.game;
    log(`promotion outcome: ${res.outcome} — ${res.message}`);
    showToast(res.message, { kind: res.outcome === "fired" ? "error" : "success" });
    renderGame();
  } catch (e) {
    logErr("requestPromotion failed", e);
    showToast(`Could not request promotion: ${e.message}`, { kind: "error" });
  }
}

async function retire() {
  const ok = await showConfirm({
    title: "Retire from your job?",
    body: "You'll live off your savings and investments. This is permanent — you can't return to your old role, though you can still look for new work later.",
    confirmText: "Retire",
    cancelText: "Keep working",
    destructive: true,
  });
  if (!ok) return;
  log("retire");
  try {
    const res = await api(`/api/game/${state.game.id}/retire`, { method: "POST" });
    state.game = res.game;
    showToast(res.message, { kind: "success" });
    renderGame();
    loadPurchases();
    loadHealthcare();
  } catch (e) {
    logErr("retire failed", e);
    showToast(`Could not retire: ${e.message}`, { kind: "error" });
  }
}

async function newGame(countryCode) {
  // Always thread the currently-selected slot through (#79). The user
  // must have picked a slot before getting here — if not, fail loud.
  const slot = slotState.pendingSlot;
  if (slot == null) {
    log("newGame called without a pending slot — bailing");
    showToast("Pick a save slot first.", { kind: "info" });
    backToSlotPicker();
    return;
  }
  log(`newGame(slot=${slot}, country=${countryCode || "random"})`);
  try {
    const body = { slot };
    if (countryCode) body.country_code = countryCode;
    // #85: stamp the active player on the game so save slots and
    // statistics filter correctly across multiple players sharing
    // the same install.
    const player = getActivePlayer();
    if (player) body.player_name = player;
    state.game = await api("/api/game/new", {
      method: "POST",
      body: JSON.stringify(body),
    });
    log(`new game created: ${state.game.id} — ${state.game.character.name} in ${state.game.country.name}`);
    slotState.pendingSlot = null;
    // Reset stale UI from any previous life (#44). Use $opt for nodes
    // that may be missing on the death screen until first death.
    $opt("#event-list").innerHTML = '<p class="placeholder">Click "Live another year" to begin your life.</p>';
    $opt("#timeline").innerHTML = "";
    $opt("#decision-modal")?.classList.add("hidden");
    $opt("#death-timeline").innerHTML = "";
    $opt("#death-summary") && ($opt("#death-summary").innerHTML = "");
    $opt("#death-diseases") && ($opt("#death-diseases").innerHTML = "");
    showGameScreen();
    renderGame();
    loadPurchases();
    loadHealthcare();
  } catch (e) {
    logErr("newGame failed", e);
    showToast(`Could not start a new life: ${e.message}`, { kind: "error" });
  }
}

async function advanceYear() {
  if (!state.game) {
    log("advanceYear called with no game");
    return;
  }
  log(`advanceYear (age ${state.game.character.age})`);
  try {
    const res = await api(`/api/game/${state.game.id}/advance`, { method: "POST" });
    state.game = res.game;
    log(`advanced to age ${res.game.character.age} — ${res.turn.events.length} events, decision=${!!res.turn.pending_decision}, died=${res.turn.died}`);
    // #90: surface achievement unlocks as toasts. Order them after the
    // death screen pop so they're not blocked by the modal.
    if (res.turn.unlocked_achievements && res.turn.unlocked_achievements.length) {
      for (const ach of res.turn.unlocked_achievements) {
        showToast(`${ach.icon} Achievement unlocked: ${ach.title}`, { kind: "info" });
      }
    }
    renderGame();
    renderTurn(res.turn);
    if (res.turn.died) showDeathScreen(res.turn);
    // #109: auto-open job board when education just completed so the
    // player can pick a career matching their new qualifications.
    else if (res.turn.education_completed && state.game.character.can_work) {
      const hasJob = !!state.game.character.job;
      showToast(
        hasJob
          ? "You graduated! Browse the job board for new opportunities."
          : "You finished your education! Time to find a job.",
        { kind: "info" }
      );
      openJobBoard();
    }
    // Refresh spending + healthcare panels (eligibility changes
    // every year as the character ages, gets new diseases, etc).
    loadPurchases();
    loadHealthcare();
  } catch (e) {
    logErr("advanceYear failed", e);
    showToast(`Failed to advance year: ${e.message}`, { kind: "error" });
  }
}

async function decide(choiceKey) {
  if (!state.game) return;
  log(`decide(${choiceKey})`);
  try {
    const res = await api(`/api/game/${state.game.id}/decision`, {
      method: "POST",
      body: JSON.stringify({ choice_key: choiceKey }),
    });
    state.game = res.game;
    renderGame();
    renderTurn(res.turn);
    // #109: auto-open job board after dropout or education decision.
    if (res.turn.education_completed && state.game.character.can_work) {
      const hasJob = !!state.game.character.job;
      showToast(
        hasJob
          ? "You graduated! Browse the job board for new opportunities."
          : "You finished your education! Time to find a job.",
        { kind: "info" }
      );
      openJobBoard();
    }
  } catch (e) {
    logErr("decide failed", e);
    showToast(`Failed to apply decision: ${e.message}`, { kind: "error" });
  }
}

// ---------- Rendering ----------
function showGameScreen() {
  $("#screen-start").classList.add("hidden");
  $("#screen-death").classList.add("hidden");
  $("#screen-statistics").classList.add("hidden");
  $("#screen-game").classList.remove("hidden");
}

async function showStartScreen() {
  $("#screen-game").classList.add("hidden");
  $("#screen-death").classList.add("hidden");
  $("#screen-statistics").classList.add("hidden");
  $("#screen-start").classList.remove("hidden");
  // Always return to the slot picker view first; never leave the
  // user staring at a country grid when they came back from a life.
  backToSlotPicker();
  // Refresh profile dropdown + slots from the server every time we
  // show the start screen so the cards reflect the latest state.
  await loadProfileDropdown();
  await loadSlots();
  renderSlotGrid();
}

// #95: render a "Marriages" section in the death screen listing every
// spouse the character ever had, with span (years married) and end state
// (divorced / widowed / still married at death). Only renders if there's
// at least one prior spouse — single-marriage characters keep the simple
// "Married: yes/no" stats row.
function renderMarriagesSection(c) {
  const prev = c.previous_spouses || [];
  const current = c.spouse;
  if (prev.length === 0) {
    // Tear down any leftover section from a previous render so the
    // archived-life view doesn't bleed state.
    const existing = document.getElementById("death-marriages");
    if (existing) existing.remove();
    return;
  }
  let host = document.getElementById("death-marriages");
  if (!host) {
    host = document.createElement("div");
    host.id = "death-marriages";
    host.className = "death-marriages";
    const diseases = document.getElementById("death-diseases");
    diseases.parentNode.insertBefore(host, diseases);
  }
  const lines = [];
  lines.push('<h3 class="ds-section-title">Marriages</h3>');
  const renderEntry = (s, label) => {
    const married = s.married_year != null;
    const span = (s.ended_year != null && s.married_year != null)
      ? ` · ${Math.max(0, s.ended_year - s.married_year)} years`
      : "";
    return `<div class="marriage-entry"><span class="m-name">${escapeHtml(s.name || "—")}</span>` +
           `<span class="m-state muted">${escapeHtml(label)}${span}</span></div>`;
  };
  for (const s of prev) {
    lines.push(renderEntry(s, s.end_state || "ended"));
  }
  if (current) {
    lines.push(renderEntry(current, "still married at death"));
  }
  host.innerHTML = lines.join("");
}

function showDeathScreen(turn) {
  $("#screen-game").classList.add("hidden");
  $("#screen-statistics").classList.add("hidden");
  $("#screen-death").classList.remove("hidden");
  // Reset the archive-only buttons; viewArchivedLife re-shows them
  // after calling showDeathScreen for the rehydrated case.
  if (!_viewingArchivedLife) {
    $opt("#btn-back-to-stats")?.classList.add("hidden");
    $opt("#btn-toggle-favorite")?.classList.add("hidden");
  }
  const c = state.game.character;
  const co = state.game.country;
  $("#death-detail").textContent =
    `${c.name} died at age ${c.age} in ${c.city}, ${co.name}. Cause: ${turn.cause_of_death}.`;

  // Life retrospective stats card (#35).
  const summary = $("#death-summary");
  summary.innerHTML = "";
  const portfolio = state.game.portfolio_value || 0;
  const netWorth = (c.money || 0) + portfolio - (c.debt || 0);
  const numDiseases = Object.keys(c.diseases || {}).length;
  const numChronics = Object.values(c.diseases || {}).filter(d => d.permanent).length;
  const numChildren = (c.children || []).length;
  const stats = [
    ["Years lived", c.age],
    ["Education", EDU_LABELS[c.education] || "none"],
    ["Final job", c.job || "—"],
    ["Final salary", c.salary ? fmtMoney(c.salary) + "/yr" : "—"],
    ["Net worth at death", fmtMoney(netWorth)],
    ["Lifestyle", c.lifestyle_tier_name || "—"],
    ["Married", c.married ? (c.spouse_name || "yes") : "no"],
    ["Children", numChildren],
    ["Diseases endured", `${numDiseases}${numChronics ? ` (${numChronics} chronic)` : ""}`],
    ["Top wisdom", c.attributes?.wisdom ?? 0],
    ["Top conscience", c.attributes?.conscience ?? 0],
  ];

  // #99: multi-leg emigration history. If the character lived in
  // more than one country across their life, render the chain
  // (origin → … → death country) so the retrospective surfaces the
  // full migrant arc, not just the final country.
  const prevCodes = c.previous_countries || [];
  if (prevCodes.length > 0) {
    const codeToName = (code) => {
      const found = (state.countries || []).find((x) => x.code === code);
      return found ? found.name : code.toUpperCase();
    };
    const chain = [...prevCodes.map(codeToName), co.name];
    stats.push(["Lived in", `${chain.join(" → ")} (${chain.length} countries)`]);
  }
  for (const [k, v] of stats) {
    const row = document.createElement("div");
    row.className = "ds-row";
    row.innerHTML = `<span>${k}</span><strong>${v}</strong>`;
    summary.appendChild(row);
  }

  // #95: marriages history. If the character had any prior spouses
  // (divorced or widowed), render a Marriages section that lists every
  // marriage with name, span, and end state. The current spouse (if
  // any) appears at the bottom as 'still married'.
  renderMarriagesSection(c);

  // Diseases list with treated/permanent annotation.
  const dis = $("#death-diseases");
  dis.innerHTML = "";
  const diseaseEntries = Object.entries(c.diseases || {});
  if (diseaseEntries.length === 0) {
    dis.innerHTML = '<p class="muted">No diseases recorded — a healthy life.</p>';
  } else {
    for (const [, d] of diseaseEntries) {
      const item = document.createElement("div");
      const tag = d.permanent ? "chronic" : (d.active ? "active" : "resolved");
      item.className = `disease ${tag}`;
      item.innerHTML = `<span class="d-name">${d.name}</span><span class="d-status">${tag} · age ${d.age_acquired}</span>`;
      dis.appendChild(item);
    }
  }

  const tl = $("#death-timeline");
  tl.innerHTML = "";
  for (const line of c.history.slice(-25)) {
    const li = document.createElement("li");
    li.textContent = line;
    tl.appendChild(li);
  }

  // #89: per-life player notes editor. Only meaningful when viewing
  // an archived life (the active death screen has no archive id yet).
  renderNotesEditor();
}

function renderNotesEditor() {
  // Only render the notes editor when viewing an archived life — the
  // live death screen doesn't have an archive id until the next
  // dashboard load.
  const existing = document.getElementById("death-notes");
  if (!_viewingArchivedLife || !_viewingArchiveId) {
    if (existing) existing.remove();
    return;
  }
  const initial = _viewingNotes || "";
  let host = existing;
  if (!host) {
    host = document.createElement("div");
    host.id = "death-notes";
    host.className = "death-notes";
    const tl = document.getElementById("death-timeline");
    if (tl && tl.parentNode) {
      tl.parentNode.insertBefore(host, tl.nextSibling);
    }
  }
  host.innerHTML = `
    <h3 class="ds-section-title">Notes</h3>
    <textarea id="death-notes-textarea" maxlength="5000" rows="4"
              placeholder="Why did this life matter? Add a note (saved on blur)."></textarea>
    <div id="death-notes-status" class="muted notes-status"></div>
  `;
  const ta = host.querySelector("#death-notes-textarea");
  const status = host.querySelector("#death-notes-status");
  ta.value = initial;
  ta.addEventListener("blur", async () => {
    if (!_viewingArchiveId) return;
    try {
      status.textContent = "Saving…";
      const res = await api(`/api/statistics/lives/${_viewingArchiveId}/notes`, {
        method: "PATCH",
        body: JSON.stringify({ notes: ta.value }),
      });
      _viewingNotes = res.notes || "";
      status.textContent = _viewingNotes ? "Saved." : "Note cleared.";
      setTimeout(() => { status.textContent = ""; }, 2000);
    } catch (e) {
      logErr("save notes failed", e);
      status.textContent = `Couldn't save: ${e.message}`;
    }
  });
}

// =====================================================================
// Cross-life statistics dashboard (#70)
// =====================================================================

// Tracks whether the current death screen is showing a live death or
// an archived life from the past-lives browser. When set, the death
// screen's "Back to statistics" button is visible and clicking
// "Live a new life" routes back to statistics instead.
let _viewingArchivedLife = false;
// Archive ID of the currently-displayed life on the death screen,
// used by the favorite toggle button. Set by viewArchivedLife().
let _viewingArchiveId = null;
let _viewingIsFavorite = false;
// #89: notes for the currently-displayed archived life. Pre-populated
// from the past-lives summary so the editor opens with the latest text.
let _viewingNotes = "";

async function showStatisticsScreen() {
  log("showStatisticsScreen");
  $("#screen-start").classList.add("hidden");
  $("#screen-game").classList.add("hidden");
  $("#screen-death").classList.add("hidden");
  $("#screen-statistics").classList.remove("hidden");
  await loadStatistics();
}

// #88: active filters on the past-lives query. Persists across
// re-renders so applying a filter then sorting/scrolling doesn't lose
// it. Cleared on screen close.
const statsFilters = {
  country: "",
  cause: "",
  job: "",
  min_age: "",
  max_age: "",
  min_net_worth: "",
  max_net_worth: "",
  name: "",
};

function _buildLivesQuery() {
  const params = new URLSearchParams();
  params.set("limit", "10");
  const player = getActivePlayer();
  if (player) params.set("player", player);
  for (const [k, v] of Object.entries(statsFilters)) {
    if (v !== "" && v != null) params.set(k, v);
  }
  return `?${params.toString()}`;
}

async function loadStatistics() {
  try {
    // #85: scope every aggregation to the active player. Empty player
    // = unscoped (legacy global view).
    const q = playerQuery();
    const livesQ = _buildLivesQuery();
    const [globalStats, byCountry, byCareer, talents, milestones, lives, favorites,
           achievements, players, facets] = await Promise.all([
      api(`/api/statistics/global${q}`),
      api(`/api/statistics/by_country${q}`),
      api(`/api/statistics/by_career${q}`),
      api(`/api/statistics/talents${q}`),
      api(`/api/statistics/milestones${q}`),
      api(`/api/statistics/lives${livesQ}`),
      api(`/api/statistics/favorites${q}`),
      api(`/api/achievements${q}`),
      api(`/api/statistics/players`),
      api(`/api/statistics/lives/facets${q}`),
    ]);
    if (globalStats.total_lives === 0) {
      $("#stats-empty").classList.remove("hidden");
    } else {
      $("#stats-empty").classList.add("hidden");
    }
    renderGlobalCard(globalStats);
    renderAchievements(achievements);
    renderMilestones(milestones);
    renderCountryTable(byCountry);
    renderCountryMap(byCountry);
    renderCareerChart(byCareer);
    renderTalents(talents);
    renderFavoritesList(favorites);
    renderPastLivesList(lives);
    renderPlayerPicker(players);
    renderFilterForm(facets);
    renderFilterChips();
  } catch (e) {
    logErr("loadStatistics failed", e);
    showToast(`Couldn't load statistics: ${e.message}`, { kind: "error" });
  }
}

// #85: render the player picker dropdown above the dashboard. Hidden
// when there's only one (or zero) players in the archive.
function renderPlayerPicker(players) {
  const host = $opt("#stats-player-picker");
  if (!host) return;
  if (!players || players.length < 1) {
    host.classList.add("hidden");
    return;
  }
  host.classList.remove("hidden");
  const select = host.querySelector("select");
  const current = getActivePlayer();
  // Rebuild options.
  select.innerHTML = '<option value="">All players</option>' +
    players.map(p => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`).join("");
  select.value = current || "";
  select.onchange = async () => {
    setActivePlayer(select.value);
    await loadStatistics();
  };
}

// #90: achievements grid. Locked entries appear grayed out and unlocked
// entries link to the archive_id of the life that triggered them.
function renderAchievements(achievements) {
  const host = $opt("#stats-achievements");
  if (!host) return;
  if (!achievements || achievements.length === 0) {
    host.innerHTML = '<p class="muted">No achievements yet.</p>';
    return;
  }
  host.innerHTML = achievements.map(a => {
    const cls = a.unlocked ? `unlocked tier-${a.tier}` : "locked";
    const click = a.unlocked && a.archive_id
      ? `data-archive-id="${escapeHtml(a.archive_id)}"`
      : "";
    return `
      <div class="achievement-card ${cls}" ${click}>
        <div class="ach-icon">${a.icon}</div>
        <div class="ach-body">
          <div class="ach-title">${escapeHtml(a.title)}</div>
          <div class="ach-desc muted">${escapeHtml(a.description)}</div>
        </div>
      </div>`;
  }).join("");
  host.querySelectorAll("[data-archive-id]").forEach((el) => {
    el.style.cursor = "pointer";
    el.onclick = () => viewArchivedLife(el.dataset.archiveId);
  });
}

// #86: country map view (region-grid heatmap). Falls back to the table
// view when toggled. Each tile = one country, colored by n_lives.
function renderCountryMap(byCountry) {
  const host = $opt("#stats-country-map");
  if (!host) return;
  if (!byCountry || byCountry.length === 0) {
    host.innerHTML = '<p class="muted">No country data yet.</p>';
    return;
  }
  // Bucket by region (pulled from the loaded country catalog).
  const codeToCountry = Object.fromEntries((state.countries || []).map(c => [c.code, c]));
  const byRegion = {};
  let maxLives = 0;
  for (const r of byCountry) {
    const code = r.country_code;
    const meta = codeToCountry[code];
    const region = (meta && meta.region) || "Other";
    if (!byRegion[region]) byRegion[region] = [];
    byRegion[region].push(r);
    if (r.n_lives > maxLives) maxLives = r.n_lives;
  }
  const regionOrder = ["North America", "Central America", "Caribbean", "South America",
                       "Europe", "Africa", "Middle East", "Asia", "Oceania"];
  const sortedRegions = Object.keys(byRegion).sort((a, b) => {
    const ai = regionOrder.indexOf(a);
    const bi = regionOrder.indexOf(b);
    if (ai === -1 && bi === -1) return a.localeCompare(b);
    if (ai === -1) return 1;
    if (bi === -1) return -1;
    return ai - bi;
  });
  const heatColor = (n) => {
    if (!n) return "rgba(20, 18, 14, 0.04)";
    const t = Math.max(0.15, n / maxLives);
    // Cream → clay heatmap.
    const r = Math.round(252 - 132 * t);
    const g = Math.round(245 - 152 * t);
    const b = Math.round(220 - 165 * t);
    return `rgb(${r}, ${g}, ${b})`;
  };
  const lines = sortedRegions.map(region => {
    const tiles = byRegion[region]
      .sort((a, b) => b.n_lives - a.n_lives)
      .map(r => `
        <div class="map-tile" style="background:${heatColor(r.n_lives)}"
             title="${escapeHtml(r.country_name)} — ${r.n_lives} lives, avg lifespan ${r.avg_lifespan}">
          <span class="map-tile-code">${r.country_code.toUpperCase()}</span>
          <span class="map-tile-n">${r.n_lives}</span>
        </div>
      `).join("");
    return `
      <div class="map-region">
        <div class="map-region-title">${escapeHtml(region)}</div>
        <div class="map-region-tiles">${tiles}</div>
      </div>`;
  });
  host.innerHTML = lines.join("");
}

// #88: filter form rendering. Builds dropdowns from /api/statistics/lives/facets.
function renderFilterForm(facets) {
  const host = $opt("#stats-filters");
  if (!host) return;
  const countryOpts = (facets.countries || []).map(c =>
    `<option value="${c.code}">${escapeHtml(c.name)}</option>`).join("");
  const causeOpts = (facets.causes || []).map(c =>
    `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");
  host.innerHTML = `
    <div class="filter-row">
      <label>Name <input type="text" id="filter-name" value="${escapeHtml(statsFilters.name)}" placeholder="substring" /></label>
      <label>Country
        <select id="filter-country">
          <option value="">any</option>${countryOpts}
        </select>
      </label>
      <label>Cause of death
        <select id="filter-cause">
          <option value="">any</option>${causeOpts}
        </select>
      </label>
      <label>Job <input type="text" id="filter-job" value="${escapeHtml(statsFilters.job)}" placeholder="substring" /></label>
      <label>Min age <input type="number" id="filter-min-age" value="${escapeHtml(statsFilters.min_age)}" min="0" max="120" /></label>
      <label>Max age <input type="number" id="filter-max-age" value="${escapeHtml(statsFilters.max_age)}" min="0" max="120" /></label>
      <label>Min net worth <input type="number" id="filter-min-nw" value="${escapeHtml(statsFilters.min_net_worth)}" /></label>
      <button id="filter-apply" class="btn xs">Apply</button>
      <button id="filter-clear" class="btn xs">Clear</button>
    </div>`;
  host.querySelector("#filter-country").value = statsFilters.country;
  host.querySelector("#filter-cause").value = statsFilters.cause;
  host.querySelector("#filter-apply").onclick = async () => {
    statsFilters.name = host.querySelector("#filter-name").value.trim();
    statsFilters.country = host.querySelector("#filter-country").value;
    statsFilters.cause = host.querySelector("#filter-cause").value;
    statsFilters.job = host.querySelector("#filter-job").value.trim();
    statsFilters.min_age = host.querySelector("#filter-min-age").value;
    statsFilters.max_age = host.querySelector("#filter-max-age").value;
    statsFilters.min_net_worth = host.querySelector("#filter-min-nw").value;
    await loadStatistics();
  };
  host.querySelector("#filter-clear").onclick = async () => {
    for (const k of Object.keys(statsFilters)) statsFilters[k] = "";
    await loadStatistics();
  };
}

// #88: render active filters as removable chips above the past-lives list.
function renderFilterChips() {
  const host = $opt("#stats-filter-chips");
  if (!host) return;
  const chips = [];
  for (const [k, v] of Object.entries(statsFilters)) {
    if (v === "" || v == null) continue;
    chips.push(`<span class="filter-chip" data-key="${k}">${escapeHtml(k)}: ${escapeHtml(String(v))} <span class="chip-x">×</span></span>`);
  }
  host.innerHTML = chips.join("");
  host.querySelectorAll(".filter-chip").forEach((el) => {
    el.onclick = async () => {
      statsFilters[el.dataset.key] = "";
      await loadStatistics();
    };
  });
}

function renderGlobalCard(s) {
  const host = $("#stats-global");
  const cells = [
    ["Total lives", s.total_lives],
    ["Distinct countries", s.distinct_countries],
    ["Average lifespan", s.avg_lifespan ? `${s.avg_lifespan} yrs` : "—"],
    ["Longest life", s.longest_lifespan ? `${s.longest_lifespan} yrs` : "—"],
    ["Lifetime earnings", fmtMoney(s.total_lifetime_earnings || 0)],
    ["Total marriages", s.total_marriages],
    ["Total children", s.total_children],
  ];
  host.innerHTML = cells.map(([k, v]) =>
    `<div class="stats-cell"><span class="stats-cell-label">${escapeHtml(k)}</span><strong class="stats-cell-value">${escapeHtml(String(v))}</strong></div>`
  ).join("");
}

function renderMilestones(m) {
  const host = $("#stats-milestones");
  const cards = [
    ["Oldest", m.oldest, (r) => `${r.age_at_death} years old`],
    ["Wealthiest", m.wealthiest, (r) => `${fmtMoney(r.lifetime_earnings)} lifetime`],
    ["Most decorated", m.most_decorated, (r) => `${r.promotion_count} promotions`],
    ["Most diseases survived", m.most_diseases_survived, (r) => `${r.diseases_count} diseases`],
    ["Most children", m.most_children, (r) => `${r.children_count} children`],
  ];
  host.innerHTML = cards.map(([title, row, fmt]) => {
    if (!row) {
      return `<div class="milestone-card empty"><div class="milestone-title">${title}</div><div class="milestone-empty muted">no lives yet</div></div>`;
    }
    return `
      <div class="milestone-card" data-archive-id="${escapeHtml(row.id)}">
        <div class="milestone-title">${title}</div>
        <div class="milestone-name">${escapeHtml(row.name)}</div>
        <div class="milestone-meta">${escapeHtml(row.country_name)}</div>
        <div class="milestone-value">${fmt(row)}</div>
      </div>`;
  }).join("");
  // Click any milestone card to view that life's retrospective.
  host.querySelectorAll("[data-archive-id]").forEach((el) => {
    el.onclick = () => viewArchivedLife(el.dataset.archiveId);
  });
}

function renderCountryTable(rows) {
  const host = $("#stats-country");
  if (!rows || rows.length === 0) {
    host.innerHTML = '<p class="muted">No data yet.</p>';
    return;
  }
  const headers = ["Country", "Lives", "Avg lifespan", "Longest", "Highest earned", "Top job", "Top cause"];
  const headerRow = headers.map((h) => `<th>${h}</th>`).join("");
  const bodyRows = rows.map((r) => `
    <tr>
      <td><strong>${escapeHtml(r.country_name)}</strong></td>
      <td>${r.n_lives}</td>
      <td>${r.avg_lifespan} yrs</td>
      <td>${r.longest_lived} yrs</td>
      <td>${fmtMoney(r.highest_earning || 0)}</td>
      <td>${escapeHtml(r.top_job || "—")}</td>
      <td>${escapeHtml(r.top_cause || "—")}</td>
    </tr>
  `).join("");
  host.innerHTML = `<table class="stats-table"><thead><tr>${headerRow}</tr></thead><tbody>${bodyRows}</tbody></table>`;
}

// #87: chart instances kept around so re-renders can dispose them
// before recreating (Chart.js requires this on the same canvas).
let _careerChartInstance = null;
let _talentsChartInstance = null;

function renderCareerChart(rows) {
  // Fall back to the CSS bar chart if Chart.js failed to load.
  if (typeof window.Chart === "undefined") {
    const host = $("#stats-career");
    host.classList.remove("hidden");
    if (!rows || rows.length === 0) {
      host.innerHTML = '<p class="muted">No data yet.</p>';
      return;
    }
    const max = Math.max(...rows.map((r) => r.n_lives), 1);
    host.innerHTML = rows.map((r) => {
      const pct = Math.round(100 * r.n_lives / max);
      return `
        <div class="stats-bar-row">
          <div class="stats-bar-label">${escapeHtml(r.job)}</div>
          <div class="stats-bar-track">
            <div class="stats-bar-fill" style="width: ${pct}%"></div>
          </div>
          <div class="stats-bar-meta">${r.n_lives} · ${fmtMoney(r.avg_earnings)} avg</div>
        </div>`;
    }).join("");
    return;
  }
  $("#stats-career").classList.add("hidden");
  const canvas = $("#stats-career-chart");
  if (_careerChartInstance) _careerChartInstance.destroy();
  if (!rows || rows.length === 0) {
    canvas.classList.add("hidden");
    return;
  }
  canvas.classList.remove("hidden");
  _careerChartInstance = new Chart(canvas, {
    type: "bar",
    data: {
      labels: rows.map(r => r.job),
      datasets: [{
        label: "Lives",
        data: rows.map(r => r.n_lives),
        backgroundColor: "rgba(132, 96, 56, 0.78)",
        borderRadius: 4,
      }],
    },
    options: {
      indexAxis: "y",
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            afterLabel: (ctx) => {
              const r = rows[ctx.dataIndex];
              return `avg earnings ${fmtMoney(r.avg_earnings)}`;
            },
          },
        },
      },
      scales: {
        x: { beginAtZero: true, ticks: { precision: 0 } },
      },
      maintainAspectRatio: false,
    },
  });
}

function renderTalents(t) {
  const attrs = ["intelligence", "artistic", "musical", "athletic", "strength", "endurance", "appearance", "conscience", "wisdom", "resistance"];
  if (typeof window.Chart === "undefined") {
    const host = $("#stats-talents");
    host.classList.remove("hidden");
    const max = Math.max(...attrs.map((a) => (t[a] && t[a].talented_count) || 0), 1);
    host.innerHTML = attrs.map((a) => {
      const stat = t[a] || { talented_count: 0, average_peak: 0 };
      const pct = Math.round(100 * stat.talented_count / max);
      return `
        <div class="stats-bar-row">
          <div class="stats-bar-label">${a}</div>
          <div class="stats-bar-track">
            <div class="stats-bar-fill talent" style="width: ${pct}%"></div>
          </div>
          <div class="stats-bar-meta">${stat.talented_count} talented · avg peak ${stat.average_peak}</div>
        </div>`;
    }).join("");
    return;
  }
  $("#stats-talents").classList.add("hidden");
  const canvas = $("#stats-talents-chart");
  if (_talentsChartInstance) _talentsChartInstance.destroy();
  canvas.classList.remove("hidden");
  _talentsChartInstance = new Chart(canvas, {
    type: "radar",
    data: {
      labels: attrs,
      datasets: [{
        label: "Average peak",
        data: attrs.map(a => (t[a] && t[a].average_peak) || 0),
        backgroundColor: "rgba(132, 96, 56, 0.18)",
        borderColor: "rgba(132, 96, 56, 0.85)",
        borderWidth: 2,
        pointBackgroundColor: "rgba(132, 96, 56, 1)",
      }],
    },
    options: {
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            afterLabel: (ctx) => {
              const stat = t[attrs[ctx.dataIndex]] || {};
              return `${stat.talented_count || 0} talented`;
            },
          },
        },
      },
      scales: {
        r: { beginAtZero: true, suggestedMax: 100 },
      },
      maintainAspectRatio: false,
    },
  });
}

function _lifeRowHtml(l) {
  const star = l.is_favorite ? '<span class="pl-star" title="favorite">★</span>' : "";
  // #89: tiny note marker if this life has player notes attached.
  const note = l.has_notes ? '<span class="pl-note" title="has notes">📝</span>' : "";
  return `
    <div class="past-life-row" data-archive-id="${escapeHtml(l.id)}">
      <div class="pl-name">${escapeHtml(l.name)} ${star} ${note}</div>
      <div class="pl-meta">
        <span>${escapeHtml(l.country_name)}</span> ·
        <span>${l.born_year}-${l.died_year}</span> ·
        <span>${l.age_at_death} yrs</span> ·
        <span>${escapeHtml(l.final_job || "—")}</span>
      </div>
      <div class="pl-cause muted">${escapeHtml(l.cause_of_death || "—")}</div>
    </div>
  `;
}

function renderFavoritesList(favorites) {
  const host = $("#stats-favorites");
  _favoritesCache = favorites || [];   // #89: cache for notes lookup
  if (!favorites || favorites.length === 0) {
    host.innerHTML = '<p class="muted">No favorites yet — view a past life and click ★ to keep it here permanently.</p>';
    return;
  }
  host.innerHTML = favorites.map(_lifeRowHtml).join("");
  host.querySelectorAll("[data-archive-id]").forEach((el) => {
    el.onclick = () => viewArchivedLife(el.dataset.archiveId);
  });
}

function renderPastLivesList(payload) {
  const host = $("#stats-lives");
  const lives = payload.lives || [];
  _pastLivesCache = lives;             // #89: cache for notes lookup
  if (lives.length === 0) {
    host.innerHTML = '<p class="muted">No archived lives yet.</p>';
    $("#stats-lives-pager").innerHTML = "";
    return;
  }
  host.innerHTML = lives.map(_lifeRowHtml).join("");
  host.querySelectorAll("[data-archive-id]").forEach((el) => {
    el.onclick = () => viewArchivedLife(el.dataset.archiveId);
  });
  $("#stats-lives-pager").innerHTML = `<span class="muted">Showing the ${lives.length} most recent of ${payload.total} total lives</span>`;
}

async function viewArchivedLife(archiveId) {
  log(`viewArchivedLife(${archiveId})`);
  try {
    const snapshot = await api(`/api/statistics/lives/${archiveId}`);
    // Hydrate the snapshot into the same shape state.game expects so
    // showDeathScreen can render it without a separate code path.
    state.game = snapshot;
    _viewingArchivedLife = true;
    _viewingArchiveId = archiveId;
    // Look up the favorite + notes state from the lists we already
    // rendered (cheap; avoids a second round trip).
    _viewingIsFavorite = _isArchiveFavorited(archiveId);
    _viewingNotes = _archiveNotesFor(archiveId);
    $("#btn-back-to-stats").classList.remove("hidden");
    _updateFavoriteButton();
    $("#btn-toggle-favorite").classList.remove("hidden");
    showDeathScreen({
      cause_of_death: snapshot.character?.cause_of_death || "—",
    });
  } catch (e) {
    logErr("viewArchivedLife failed", e);
    showToast(`Couldn't load that life: ${e.message}`, { kind: "error" });
  }
}

// #89: pull notes for an archived life out of whatever rendered list
// we already have so the editor opens with the latest text without a
// second round trip. The PATCH endpoint is the source of truth on save.
function _archiveNotesFor(archiveId) {
  // Search the past-lives + favorites lists for an entry with this id.
  // Both lists carry data attributes via _lifeRowHtml; the underlying
  // data lives on a per-list cache we set during render.
  const lists = [_pastLivesCache, _favoritesCache];
  for (const cache of lists) {
    if (!cache) continue;
    const found = cache.find((l) => l.id === archiveId);
    if (found) return found.notes || "";
  }
  return "";
}

// Caches populated by renderPastLivesList / renderFavoritesList so the
// notes lookup above can avoid an extra fetch.
let _pastLivesCache = null;
let _favoritesCache = null;

function _isArchiveFavorited(archiveId) {
  // Look at the rendered favorites list (data attributes) — quicker
  // than another fetch. If the favorites list isn't rendered yet,
  // assume false; the toggle will set it correctly.
  const favHost = $opt("#stats-favorites");
  if (!favHost) return false;
  return !!favHost.querySelector(`[data-archive-id="${archiveId.replace(/"/g, '\\"')}"]`);
}

function _updateFavoriteButton() {
  const btn = $opt("#btn-toggle-favorite");
  if (!btn) return;
  if (_viewingIsFavorite) {
    btn.textContent = "★ Remove from favorites";
    btn.classList.add("favorited");
  } else {
    btn.textContent = "☆ Add to favorites";
    btn.classList.remove("favorited");
  }
}

async function toggleFavorite() {
  if (!_viewingArchiveId) return;
  const newState = !_viewingIsFavorite;
  log(`toggleFavorite(${_viewingArchiveId}, ${newState})`);
  try {
    const r = await fetch(`/api/statistics/lives/${_viewingArchiveId}/favorite`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_favorite: newState }),
    });
    if (!r.ok) {
      const msg = await r.text();
      throw new Error(`${r.status}: ${msg}`);
    }
    _viewingIsFavorite = newState;
    _updateFavoriteButton();
    showToast(newState ? "Added to favorites" : "Removed from favorites", { kind: "success" });
  } catch (e) {
    logErr("toggleFavorite failed", e);
    showToast(`Couldn't update favorite: ${e.message}`, { kind: "error" });
  }
}

async function clearNonFavorites() {
  const ok = await showConfirm({
    title: "Clear non-favorited lives?",
    body: "This permanently deletes every archived life that isn't marked as a favorite. The JSONL backup file will be rewritten too. Use this to wipe test/cruft data.",
    confirmText: "Clear",
    cancelText: "Cancel",
    destructive: true,
  });
  if (!ok) return;
  log("clearNonFavorites");
  try {
    const r = await fetch("/api/statistics/clear_non_favorites", { method: "POST" });
    if (!r.ok) {
      const msg = await r.text();
      throw new Error(`${r.status}: ${msg}`);
    }
    const result = await r.json();
    showToast(`Cleared ${result.deleted} non-favorited live${result.deleted === 1 ? "" : "s"}`, { kind: "success" });
    await loadStatistics();
  } catch (e) {
    logErr("clearNonFavorites failed", e);
    showToast(`Couldn't clear archive: ${e.message}`, { kind: "error" });
  }
}

async function exportArchive() {
  // Browser handles the actual download via the <a href download> link
  // — this function only exists if we ever need a programmatic path.
}

function importArchive() {
  $("#stats-import-input").click();
}

async function handleArchiveImport(file) {
  log(`importing archive from ${file.name}`);
  try {
    const text = await file.text();
    const r = await fetch("/api/statistics/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: text,
    });
    if (!r.ok) {
      const msg = await r.text();
      throw new Error(`${r.status}: ${msg}`);
    }
    const result = await r.json();
    showToast(
      `Imported ${result.imported} new live${result.imported === 1 ? "" : "s"} (${result.skipped} skipped)`,
      { kind: "success" },
    );
    await loadStatistics();
  } catch (e) {
    logErr("import failed", e);
    showToast(`Import failed: ${e.message}`, { kind: "error" });
  }
}

// Collapse consecutive identical-suffix history lines into a range +
// count (#80). Each line is "Age N: ..." — we strip the age prefix to
// compare the body and rebuild as "Age N-M: body (Kx)".
function groupTimelineLines(lines) {
  const out = [];
  let i = 0;
  const re = /^Age (\d+): (.*)$/;
  while (i < lines.length) {
    const m = re.exec(lines[i]);
    if (!m) {
      out.push(lines[i]);
      i++;
      continue;
    }
    const startAge = parseInt(m[1], 10);
    const body = m[2];
    let j = i + 1;
    let endAge = startAge;
    let count = 1;
    while (j < lines.length) {
      const mj = re.exec(lines[j]);
      if (!mj || mj[2] !== body) break;
      endAge = parseInt(mj[1], 10);
      count++;
      j++;
    }
    if (count === 1) {
      out.push(lines[i]);
    } else if (count === 2) {
      // Render two-in-a-row as both lines (grouping a pair feels
      // unnecessary).
      out.push(lines[i]);
      out.push(lines[i + 1]);
    } else {
      out.push(`Age ${startAge}-${endAge}: ${body} (${count}×)`);
    }
    i = j;
  }
  return out;
}

function fmtMoney(n) {
  if (n === undefined || n === null) return "—";
  const sign = n < 0 ? "-" : "";
  return sign + "$" + Math.abs(Math.round(n)).toLocaleString();
}

const ATTR_LABELS = [
  "health", "happiness", "intelligence", "artistic", "musical", "athletic",
  "strength", "endurance", "appearance", "conscience", "wisdom", "resistance",
];

const EDU_LABELS = ["none", "primary", "secondary", "vocational", "university"];

function renderGame() {
  const g = state.game;
  if (!g) return;
  const c = g.character;
  const co = g.country;

  $("#flag").src = `/flags/${co.code}.bmp`;
  $("#flag").alt = co.name;
  $("#char-name").textContent = c.name;

  // Property scene — pixel-art view of owned possessions.
  if (typeof PropertyScene !== "undefined") {
    PropertyScene.render($opt("#property-canvas"), c);
  }
  const where = `${c.city}, ${co.name}`;
  $("#char-where").textContent = c.is_urban === false ? `${where} · rural` : where;

  $("#stat-age").textContent = c.age;
  $("#stat-year").textContent = g.year;
  // Education stat shows the credential level, plus "in <track> school"
  // when currently enrolled — gives the player a clear signal during
  // multi-year programs (vocational, university) that they're still in
  // school and aren't expected to be working full-time.
  const eduLevel = EDU_LABELS[c.education] || "—";
  if (c.in_school && c.school_track) {
    $("#stat-edu").textContent = `${eduLevel} · in ${c.school_track} school`;
  } else if (c.in_school) {
    $("#stat-edu").textContent = `${eduLevel} · in school`;
  } else {
    $("#stat-edu").textContent = eduLevel;
  }
  $("#stat-job").textContent = c.job || "—";
  $("#btn-quit-job").classList.toggle("hidden", !c.job);

  // Find Work button + work-blocked label (#57). Shown only when the
  // character is old enough + not in primary school.
  const findBtn = $opt("#btn-find-work");
  const blocked = $opt("#work-blocked");
  if (findBtn && blocked) {
    if (c.can_work) {
      findBtn.classList.remove("hidden");
      blocked.classList.add("hidden");
      blocked.textContent = "";
    } else {
      findBtn.classList.add("hidden");
      if (c.work_blocked_reason) {
        blocked.classList.remove("hidden");
        blocked.textContent = c.work_blocked_reason;
      } else {
        blocked.classList.add("hidden");
      }
    }
  }

  // Drop out of school button (#69) — visible when in school AND old
  // enough to work in this country.
  const dropBtn = $opt("#btn-drop-out");
  if (dropBtn) {
    dropBtn.classList.toggle("hidden", !c.can_drop_out);
  }
  // #107: Enroll in university button — visible when eligible.
  const enrollBtn = $opt("#btn-enroll-uni");
  if (enrollBtn) {
    enrollBtn.classList.toggle("hidden", !c.can_enroll_university);
  }
  // #49: Move abroad button — visible from age 16 onward.
  const emigrateBtn = $opt("#btn-emigrate");
  if (emigrateBtn) {
    emigrateBtn.classList.toggle("hidden", c.age < 16);
  }
  $("#stat-salary").textContent = c.salary ? fmtMoney(c.salary) + "/yr" : "—";
  $("#stat-money").textContent = fmtMoney(c.money);
  // #113: lifestyle tier badge with icon
  const lifestyleEl = $opt("#stat-lifestyle");
  if (lifestyleEl) {
    const tier = c.lifestyle_tier ?? 3;
    const tierIcon = (typeof ICONS !== "undefined" && ICONS["tier_" + tier]) || "";
    lifestyleEl.innerHTML = (tierIcon ? `<span class="tier-icon">${tierIcon}</span>` : "") + escapeHtml(c.lifestyle_tier_name || "—");
    lifestyleEl.className = "lifestyle-badge tier-" + tier;
  }
  // #113: lifestyle budget selector (age 18+)
  const budgetRow = $opt("#budget-row");
  const budgetSel = $opt("#budget-select");
  if (budgetRow && budgetSel) {
    if (c.age >= 18) {
      budgetRow.classList.remove("hidden");
      const opts = c.budget_options || [];
      // Only rebuild options if the count changed (avoids flicker).
      if (budgetSel.options.length !== opts.length) {
        budgetSel.innerHTML = "";
        for (const o of opts) {
          const opt = document.createElement("option");
          opt.value = o.level;
          opt.textContent = `${o.label} (${fmtMoney(o.yearly_cost)}/yr)`;
          budgetSel.appendChild(opt);
        }
        budgetSel.onchange = async () => {
          const level = parseInt(budgetSel.value, 10);
          try {
            const res = await api(`/api/game/${state.game.id}/set_budget`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ level }),
            });
            state.game = res;
            renderGame();
            showToast(`Budget set to ${budgetSel.options[budgetSel.selectedIndex].textContent.split(" (")[0]}`, { kind: "info" });
          } catch (e) {
            logErr("set_budget failed", e);
          }
        };
      }
      budgetSel.value = c.lifestyle_budget ?? 2;
    } else {
      budgetRow.classList.add("hidden");
    }
  }
  $("#stat-portfolio").textContent = fmtMoney(g.portfolio_value || 0);
  $("#stat-debt").textContent = fmtMoney(c.debt || 0);
  $("#stat-married").textContent = c.married ? (c.spouse_name || "yes") : "no";
  $("#stat-kids").textContent = (c.children || []).length;
  // Try for child button — visible when married and eligible.
  const tryChildBtn = $opt("#btn-try-child");
  if (tryChildBtn) {
    tryChildBtn.classList.toggle("hidden", !c.can_try_for_child);
    if (c.try_for_child_reason && !c.can_try_for_child) {
      tryChildBtn.title = c.try_for_child_reason;
    }
  }

  // #50: spouse card with attributes, salary, age. Hidden when not
  // married (or only dating). The spouse object is the source of
  // truth — c.married is derived from spouse.married_year != null.
  const sp = c.spouse;
  const spouseSection = $opt("#spouse-section");
  if (spouseSection) {
    if (sp && c.married) {
      spouseSection.classList.remove("hidden");
      const aliveTag = sp.alive ? "" : ' <span class="muted">· deceased</span>';
      const jobLine = sp.job ? `${escapeHtml(sp.job)} · ${fmtMoney(sp.salary)}/yr` : "(no income)";
      const attrs = sp.attributes || {};
      const attrBars = ["intelligence", "appearance", "wisdom", "conscience"]
        .map((k) => {
          const v = attrs[k] || 0;
          return `<div class="sa-row"><span>${k}</span><div class="sa-bar"><span style="width:${v}%"></span></div><strong>${v}</strong></div>`;
        }).join("");
      $opt("#spouse-card").innerHTML = `
        <div class="spouse-name"><strong>${escapeHtml(sp.name)}</strong>${aliveTag}</div>
        <div class="muted">${escapeHtml(jobLine)}</div>
        <div class="muted">age ${sp.age} · compatibility ${sp.compatibility}</div>
        <div class="spouse-attrs">${attrBars}</div>`;
    } else {
      spouseSection.classList.add("hidden");
    }
  }

  // Headline health bar (always visible — #47)
  const hh = $("#health-headline");
  const h = c.attributes?.health ?? 0;
  let band = "good";
  if (h < 30) band = "critical";
  else if (h < 60) band = "warning";
  hh.innerHTML = `
    <div class="health-label">
      <span>Health</span><strong>${h}</strong>
    </div>
    <div class="bar"><span class="${band}" style="width:${h}%"></span></div>`;

  // Career card (#51) — vocation field, category, ladder progress
  const careerEl = $opt("#career-card");
  if (careerEl) {
    const career = g.career;
    if (!career) {
      careerEl.classList.add("hidden");
      careerEl.innerHTML = "";
    } else {
      careerEl.classList.remove("hidden");
      const ladderProgress = Math.min(100, Math.round(100 * career.years_in_role / career.years_to_promote));
      // #83: a true entrepreneur is freelance with no next rung in the
      // ladder. Promotable freelancers (writer → published author,
      // artist → exhibited artist) keep their normal ladder UI.
      const isEntrepreneur = !!career.is_freelance && !career.next_job;

      let nextLine = "";
      let gatesLine = "";
      if (career.next_job) {
        const stepLabel = career.next_is_seniority_step ? "Next step" : "Next";
        nextLine = `<div class="career-next">${stepLabel}: <strong>${escapeHtml(career.next_job)}</strong> (${career.years_to_promote} yrs in role)</div>`;
        // Surface every requirement the player is currently failing
        // for the next rung — education, IQ, age, urban/rural — so
        // they aren't forced to click to discover the gate.
        const missing = career.next_missing_requirements || [];
        if (missing.length) {
          const chips = missing.map((m) => `<span class="gate-chip">${escapeHtml(m)}</span>`).join("");
          gatesLine = `<div class="career-gates">Needs ${chips}</div>`;
        }
      } else if (isEntrepreneur) {
        nextLine = `<div class="career-next muted">Self-employed — earnings vary year to year based on talent and luck.</div>`;
      } else {
        nextLine = `<div class="career-next muted">Top of the ladder.</div>`;
      }
      const cat = career.vocation_field || career.category || "—";
      const eligibleByYears = career.years_in_role >= career.years_to_promote;

      // Three buttons (#63 + #82): salary raise, promotion, and retire.
      // Each shows enabled when can_*, OR a clickable .blocked variant
      // that toasts the reason on click. Disabled <button>s swallow
      // clicks silently and leave the player wondering why nothing
      // happens — always show a clickable button with feedback on the
      // blocked path.
      //
      // #83: true entrepreneurs (freelance + no ladder) skip the raise
      // and promotion buttons entirely — they don't have a boss or a
      // ladder to climb. They keep the Retire button.
      const raiseLive    = !!career.can_request_raise;
      const promoLive    = !!career.can_request_promotion;
      const retireLive   = !!career.can_retire;
      const showRaiseBtn = !isEntrepreneur && (raiseLive || eligibleByYears);
      const showPromoBtn = !isEntrepreneur && (promoLive || (eligibleByYears && career.next_job));
      // Retire is always offered when employed — the blocked variant
      // surfaces the age / wealth gate up-front.
      const showRetireBtn = !!career.current_job;

      const raiseBtn = !showRaiseBtn ? "" :
        raiseLive
          ? `<button id="btn-ask-raise" class="btn xs">Ask for raise</button>`
          : `<button id="btn-ask-raise-blocked" class="btn xs blocked" data-reason="${escapeHtml(career.raise_blocked_reason || "not eligible")}">Ask for raise</button>`;
      const promoBtn = !showPromoBtn ? "" :
        promoLive
          ? `<button id="btn-ask-promo" class="btn xs">Ask for promotion</button>`
          : `<button id="btn-ask-promo-blocked" class="btn xs blocked" data-reason="${escapeHtml(career.promotion_blocked_reason || "not eligible")}">Ask for promotion</button>`;
      const retireBtn = !showRetireBtn ? "" :
        retireLive
          ? `<button id="btn-retire" class="btn xs">Retire</button>`
          : `<button id="btn-retire-blocked" class="btn xs blocked" data-reason="${escapeHtml(career.retire_blocked_reason || "not eligible")}">Retire</button>`;

      // Years label — for ladder jobs show progress toward promotion;
      // for entrepreneurs just show how long they've been at it.
      const yearsLabel = isEntrepreneur
        ? `${career.years_in_role} year${career.years_in_role === 1 ? "" : "s"} self-employed`
        : `${career.years_in_role} / ${career.years_to_promote} yrs in role`;
      // Hide the ladder progress bar for entrepreneurs (no ladder).
      const barHtml = isEntrepreneur
        ? ""
        : `<div class="career-bar"><span style="width:${ladderProgress}%"></span></div>`;

      careerEl.innerHTML = `
        <div class="career-head">
          <span class="career-cat">${cat}${career.is_freelance ? ' <span class="career-freelance-tag">freelance</span>' : ""}</span>
          <span class="career-promos">${career.promotion_count > 0 ? career.promotion_count + " promotion" + (career.promotion_count === 1 ? "" : "s") : ""}${career.is_seniority_step ? (career.promotion_count > 0 ? " · " : "") + "seniority tier" : ""}</span>
        </div>
        ${barHtml}
        <div class="career-yrs">${yearsLabel}</div>
        ${nextLine}
        ${gatesLine}
        ${(raiseBtn || promoBtn || retireBtn) ? `<div class="career-actions">${raiseBtn} ${promoBtn} ${retireBtn}</div>` : ""}
      `;
      const rb = $opt("#btn-ask-raise");
      if (rb) rb.addEventListener("click", requestRaise);
      const pb = $opt("#btn-ask-promo");
      if (pb) pb.addEventListener("click", requestPromotion);
      const retireB = $opt("#btn-retire");
      if (retireB) retireB.addEventListener("click", retire);
      const rbBlocked = $opt("#btn-ask-raise-blocked");
      if (rbBlocked) rbBlocked.addEventListener("click", () => showToast(rbBlocked.dataset.reason, { kind: "info" }));
      const pbBlocked = $opt("#btn-ask-promo-blocked");
      if (pbBlocked) pbBlocked.addEventListener("click", () => showToast(pbBlocked.dataset.reason, { kind: "info" }));
      const retireBlocked = $opt("#btn-retire-blocked");
      if (retireBlocked) retireBlocked.addEventListener("click", () => showToast(retireBlocked.dataset.reason, { kind: "info" }));
    }
  }

  renderFinances();

  // Attributes
  const attrEl = $("#attrs");
  attrEl.innerHTML = "";
  for (const k of ATTR_LABELS) {
    const v = c.attributes[k];
    const row = document.createElement("div");
    row.className = "attr";
    row.innerHTML = `
      <span class="label">${k}</span>
      <div class="bar"><span style="width:${v}%"></span></div>
      <span class="val">${v}</span>
    `;
    attrEl.appendChild(row);
  }

  // Diseases
  const diseasesEl = $("#diseases");
  diseasesEl.innerHTML = "";
  const ds = c.diseases || {};
  const entries = Object.entries(ds);
  if (entries.length === 0) {
    diseasesEl.innerHTML = '<p class="placeholder">Healthy.</p>';
  } else {
    for (const [key, info] of entries) {
      const li = document.createElement("div");
      li.className = "disease " + (info.active ? "active" : "resolved");
      const status = info.active
        ? (info.permanent ? "chronic" : "active")
        : "resolved";
      li.innerHTML = `<span class="d-name">${info.name}</span><span class="d-status">${status}</span>`;
      diseasesEl.appendChild(li);
    }
  }

  // Country panel
  const ci = $("#country-info");
  ci.innerHTML = "";

  // Status badges from the 2007 binary (#30): at_war, conscription
  const badges = [];
  if (co.at_war) badges.push(["At war", "badge-war"]);
  if (co.military_conscription) badges.push(["Conscription", "badge-conscript"]);
  if (badges.length) {
    const badgeWrap = document.createElement("div");
    badgeWrap.className = "country-badges";
    for (const [label, cls] of badges) {
      const b = document.createElement("span");
      b.className = `badge ${cls}`;
      b.textContent = label;
      badgeWrap.appendChild(b);
    }
    ci.appendChild(badgeWrap);
  }

  if (co.description) {
    const desc = document.createElement("p");
    desc.className = "country-desc";
    desc.textContent = co.description;
    ci.appendChild(desc);
  }
  const ciRows = [
    ["Region", co.region],
    ["Population", co.population.toLocaleString()],
    ["GDP per capita", fmtMoney(co.gdp_pc)],
    ["Life expectancy", co.life_expectancy + " yrs"],
    ["Infant mortality", co.infant_mortality + " / 1000"],
    ["Literacy", co.literacy + "%"],
    ["Capital", co.capital],
    ["Currency", co.currency],
    ["Religion", co.primary_religion],
    ["Language", co.primary_language],
  ];
  for (const [k, v] of ciRows) {
    const row = document.createElement("div");
    row.className = "ci-row";
    row.innerHTML = `<span>${k}</span><span>${v}</span>`;
    ci.appendChild(row);
  }

  // 2007 binary facts: human-rights flags, military service, disaster history.
  // Surfaced from country_binary_field (#30). Empty for #7 territory additions.
  if (co.binary_facts) {
    const facts = co.binary_facts;
    const hrEntries = Object.entries(facts.human_rights || {}).filter(([, v]) => v === true);
    if (hrEntries.length) {
      const h = document.createElement("h5");
      h.className = "facts-heading";
      h.textContent = "Human rights concerns (2007)";
      ci.appendChild(h);
      const grid = document.createElement("div");
      grid.className = "facts-grid";
      const labels = {
        Torture: "Torture",
        PoliticalPrisoners: "Political prisoners",
        ExtrajudicialExecutions: "Extrajudicial executions",
        CruelPunishment: "Cruel punishment",
        Impunity: "Impunity for officials",
        UnfairTrials: "Unfair trials",
        WomensRights: "Women's rights restricted",
        ForcibleReturn: "Forcible refugee return",
        Journalists: "Journalists at risk",
        HumanRightsDefenders: "Defenders at risk",
        PrisonConditions: "Poor prison conditions",
      };
      for (const [k] of hrEntries) {
        const item = document.createElement("span");
        item.className = "fact-flag";
        item.textContent = labels[k] || k;
        grid.appendChild(item);
      }
      ci.appendChild(grid);
    }

    const ms = facts.military_service || {};
    if (ms.MilitaryConscription || ms.AlternativeService) {
      const h = document.createElement("h5");
      h.className = "facts-heading";
      h.textContent = "Military service (2007)";
      ci.appendChild(h);
      const lines = [];
      if (ms.MilitaryConscription) lines.push("Mandatory conscription in effect");
      if (ms.AlternativeService) lines.push("Alternative civilian service available");
      if (typeof ms.MonthsService === "number" && ms.MonthsService > 0)
        lines.push(`Service length: ${ms.MonthsService} months`);
      const ul = document.createElement("ul");
      ul.className = "facts-list";
      for (const line of lines) {
        const li = document.createElement("li");
        li.textContent = line;
        ul.appendChild(li);
      }
      ci.appendChild(ul);
    }

    // Disaster history is now an array of {kind, events, killed_per_event,
    // affected_per_event} records (#34). Render as "N events, ~K deaths,
    // ~A affected each" so it's clear the values are per-event averages,
    // not cumulative totals.
    const dh = facts.disaster_history || [];
    if (dh.length) {
      const h = document.createElement("h5");
      h.className = "facts-heading";
      h.textContent = "Disaster history (per typical event)";
      ci.appendChild(h);
      const ul = document.createElement("ul");
      ul.className = "facts-list";
      const labelMap = {
        earthquake: "Earthquakes",
        flood: "Floods",
        famine: "Famines",
        fire: "Fires",
        avalanche: "Avalanches",
      };
      const fmt = (n) => n.toLocaleString();
      // Sort by events count descending — countries with more recorded
      // events go first.
      const sorted = [...dh].sort((a, b) => b.events - a.events);
      for (const d of sorted) {
        const li = document.createElement("li");
        const parts = [`${d.events} recorded`];
        if (d.killed_per_event && d.killed_per_event > 0) {
          parts.push(`~${fmt(d.killed_per_event)} killed`);
        }
        if (d.affected_per_event && d.affected_per_event > 0) {
          parts.push(`~${fmt(d.affected_per_event)} affected`);
        }
        li.innerHTML = `<strong>${labelMap[d.kind] || d.kind}</strong>: ${parts.join(", ")}`;
        ul.appendChild(li);
      }
      ci.appendChild(ul);
    }
  }

  // Year title
  $("#year-title").textContent = `Age ${c.age} · Year ${g.year}`;

  // Timeline (#80) — group consecutive identical events into a single
  // line so a 70-year Diwali run renders as one entry instead of 70.
  const tl = $("#timeline");
  tl.innerHTML = "";
  const groupedLines = groupTimelineLines(c.history.slice(-100));
  for (const line of groupedLines.slice(-50).reverse()) {
    const li = document.createElement("li");
    li.textContent = line;
    tl.appendChild(li);
  }

  // Pending decision (#46): pop a modal so the player can't miss it.
  const modal = $("#decision-modal");
  if (g.pending_event) {
    modal.classList.remove("hidden");
    $("#decision-title").textContent = g.pending_event.title;
    $("#decision-desc").textContent = g.pending_event.description;
    const btns = $("#decision-buttons");
    btns.innerHTML = "";
    // #91: events that ship a `candidates` payload (MEET_CANDIDATES)
    // get a card grid above the choice buttons so the player can see
    // who they're picking. The choice buttons stay below as the
    // commit action.
    const cardHost = ensureCandidateCardHost();
    if (g.pending_event.candidates && g.pending_event.candidates.length) {
      renderCandidateCards(cardHost, g.pending_event.candidates);
    } else {
      cardHost.innerHTML = "";
      cardHost.classList.add("hidden");
    }
    for (const ch of g.pending_event.choices) {
      const b = document.createElement("button");
      b.className = "btn";
      b.textContent = ch.label;
      b.onclick = () => decide(ch.key);
      btns.appendChild(b);
    }
    $("#btn-advance").disabled = true;
  } else {
    modal.classList.add("hidden");
    $("#btn-advance").disabled = !c.alive;
  }
}

// #91: build (and cache) a card grid host directly above the decision
// modal's button row. Lazily injected so existing choice events keep
// rendering identically when no candidates are present.
function ensureCandidateCardHost() {
  let host = document.getElementById("candidate-cards");
  if (host) return host;
  host = document.createElement("div");
  host.id = "candidate-cards";
  host.className = "candidate-cards hidden";
  const btns = document.getElementById("decision-buttons");
  if (btns && btns.parentNode) {
    btns.parentNode.insertBefore(host, btns);
  }
  return host;
}

function renderCandidateCards(host, candidates) {
  host.innerHTML = "";
  host.classList.remove("hidden");
  candidates.forEach((cand, idx) => {
    const card = document.createElement("div");
    card.className = "candidate-card";
    const attrs = cand.attributes || {};
    const compat = cand.compatibility ?? "?";
    const job = cand.job || "—";
    card.innerHTML = `
      <div class="cc-head">
        <span class="cc-name">${escapeHtml(cand.name || "—")}</span>
        <span class="cc-age muted">age ${cand.age ?? "—"}</span>
      </div>
      <div class="cc-job muted">${escapeHtml(job)}</div>
      <div class="cc-attrs">
        <span title="Intelligence">int ${attrs.intelligence ?? "—"}</span>
        <span title="Appearance">app ${attrs.appearance ?? "—"}</span>
        <span title="Conscience">con ${attrs.conscience ?? "—"}</span>
        <span title="Wisdom">wis ${attrs.wisdom ?? "—"}</span>
      </div>
      <div class="cc-compat">compatibility <strong>${compat}</strong></div>
      <button class="btn cc-pick" data-idx="${idx}">Pick this one</button>
    `;
    card.querySelector(".cc-pick").addEventListener("click", () => {
      decide(`pick_${idx}`);
    });
    host.appendChild(card);
  });
}

function renderTurn(turn) {
  const list = $("#event-list");
  list.innerHTML = "";
  if (!turn.events || turn.events.length === 0) {
    const p = document.createElement("p");
    p.className = "placeholder";
    p.textContent = "Quiet year. Nothing notable happened.";
    list.appendChild(p);
    return;
  }
  for (const ev of turn.events) {
    const node = document.createElement("div");
    // Compute net polarity from deltas + money_delta to color the card
    // (#45). Positive net → "good" (green tint), negative → "bad" (red),
    // zero/mixed → category color (existing behavior).
    let net = 0;
    if (ev.deltas) {
      for (const v of Object.values(ev.deltas)) net += v;
    }
    if (ev.money_delta) net += ev.money_delta > 0 ? 1 : -1;
    const polarity = net > 0 ? "good" : net < 0 ? "bad" : "neutral";
    node.className = `event ${ev.category} polarity-${polarity}`;
    let deltas = "";
    if (ev.deltas) {
      for (const [k, v] of Object.entries(ev.deltas)) {
        if (!v) continue;
        const cls = v > 0 ? "up" : "down";
        deltas += `<span class="delta ${cls}">${k} ${v > 0 ? "+" : ""}${v}</span>`;
      }
    }
    if (ev.money_delta) {
      const cls = ev.money_delta > 0 ? "up" : "down";
      deltas += `<span class="delta ${cls}">${fmtMoney(ev.money_delta)}</span>`;
    }
    node.innerHTML = `
      <div class="e-title">${ev.title}</div>
      <div class="e-summary">${ev.summary}</div>
      ${deltas ? `<div class="e-deltas">${deltas}</div>` : ""}
    `;
    list.appendChild(node);
  }
}

// ---------- Finances pane ----------
function renderFinances() {
  const c = state.game?.character;
  if (!c) return;

  // Header summary (#81): portfolio + debt + cash one-liner so the
  // panel always has useful info even when empty.
  const sumEl = $opt("#finances-summary");
  if (sumEl) {
    const portfolio = state.game.portfolio_value || 0;
    const parts = [
      `<span class="fs-label">Cash</span> <strong>${fmtMoney(c.money)}</strong>`,
    ];
    if (portfolio) parts.push(`<span class="fs-label">Portfolio</span> <strong>${fmtMoney(portfolio)}</strong>`);
    if (c.debt) parts.push(`<span class="fs-label">Debt</span> <strong>${fmtMoney(c.debt)}</strong>`);
    sumEl.innerHTML = parts.join(" · ");
  }

  // Open investments list
  const invHost = $("#open-investments");
  invHost.innerHTML = "";
  const invs = c.investments || [];
  if (invs.length === 0) {
    invHost.innerHTML = '<p class="placeholder">No open investments yet — start with a savings account ($100 minimum) and let it compound.</p>';
  } else {
    invs.forEach((inv, i) => {
      const pl = inv.value - inv.cost_basis;
      const lifeCls = pl >= 0 ? "up" : "down";
      const yoy = inv.last_year_delta || 0;
      const yoyCls = yoy >= 0 ? "up" : "down";
      const yoyChip = yoy !== 0
        ? `<span class="delta ${yoyCls}">${yoy >= 0 ? "+" : ""}${fmtMoney(yoy)} this yr</span>`
        : "";
      const row = document.createElement("div");
      row.className = "holding";
      row.innerHTML = `
        <div class="h-name">${inv.name}</div>
        <div class="h-meta">cost ${fmtMoney(inv.cost_basis)} · value <strong>${fmtMoney(inv.value)}</strong>
          <span class="delta ${lifeCls}">${pl >= 0 ? "+" : ""}${fmtMoney(pl)} lifetime</span>
          ${yoyChip}</div>
        <button class="btn sm" data-sell="${i}">Sell</button>`;
      invHost.appendChild(row);
    });
    invHost.querySelectorAll("[data-sell]").forEach((b) => {
      b.onclick = () => sellInvestment(parseInt(b.dataset.sell, 10));
    });
  }

  // Investment product dropdown — filter by character age (#68).
  const invSel = $("#invest-product");
  const eligibleInvs = state.investmentProducts.filter((p) => c.age >= (p.min_age || 0));
  invSel.innerHTML = "";
  if (eligibleInvs.length === 0) {
    const opt = document.createElement("option");
    opt.disabled = true;
    opt.selected = true;
    opt.textContent = "Too young to invest";
    invSel.appendChild(opt);
  } else {
    for (const p of eligibleInvs) {
      const opt = document.createElement("option");
      opt.value = p.id;
      const lo = (p.annual_return_low * 100).toFixed(0);
      const hi = (p.annual_return_high * 100).toFixed(0);
      opt.textContent = `${p.name} (${lo}% – ${hi}% / yr, min ${fmtMoney(p.min_amount)})`;
      invSel.appendChild(opt);
    }
  }
  // Disable the invest form when no products are available.
  const invForm = $("#invest-form");
  const invInput = $("#invest-amount");
  const invBtn = invForm.querySelector("button");
  invInput.disabled = eligibleInvs.length === 0;
  invBtn.disabled = eligibleInvs.length === 0;

  // Open loans list with manual repay control (#40).
  const loanHost = $("#open-loans");
  loanHost.innerHTML = "";
  const loans = c.loans || [];
  if (loans.length === 0) {
    loanHost.innerHTML = '<p class="placeholder">No open loans. Borrow against future income if you need cash for a big purchase or investment.</p>';
  } else {
    loans.forEach((l, i) => {
      const row = document.createElement("div");
      row.className = "holding";
      row.innerHTML = `
        <div class="h-name">${l.name}</div>
        <div class="h-meta">balance <strong>${fmtMoney(l.balance)}</strong>
          · ${(l.interest_rate * 100).toFixed(1)}% APR
          · ${l.years_remaining} yrs left</div>
        <div class="loan-pay-row">
          <input type="number" min="1" placeholder="Pay extra" data-pay-input="${i}" />
          <button class="btn sm" data-pay-loan="${i}">Pay</button>
        </div>`;
      loanHost.appendChild(row);
    });
    loanHost.querySelectorAll("[data-pay-loan]").forEach((b) => {
      b.onclick = async () => {
        const i = parseInt(b.dataset.payLoan, 10);
        const input = loanHost.querySelector(`[data-pay-input="${i}"]`);
        const amount = parseInt(input.value, 10);
        if (!amount || amount <= 0) return;
        try {
          await payLoan(i, amount);
        } catch (e) {
          showToast(e.message, { kind: "error" });
        }
      };
    });
  }

  // Loan product dropdown — filter by character age (#37). Family loans
  // open up at 14, all other loans at 18.
  const loanSel = $("#loan-product");
  const eligible = state.loanProducts.filter((p) => {
    const minAge = p.name === "family loan" ? 14 : 18;
    return c.age >= minAge;
  });
  loanSel.innerHTML = "";
  if (eligible.length === 0) {
    const opt = document.createElement("option");
    opt.disabled = true;
    opt.selected = true;
    opt.textContent = c.age < 14 ? "Too young to borrow" : "Too young for non-family loans";
    loanSel.appendChild(opt);
  } else {
    for (const p of eligible) {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = `${p.name} (max ${fmtMoney(p.max_amount)}, ${(p.interest_rate * 100).toFixed(0)}% / ${p.max_years} yrs)`;
      loanSel.appendChild(opt);
    }
  }
  // Disable the borrow form when no loans are available.
  const loanForm = $("#loan-form");
  const loanInput = $("#loan-amount");
  const loanBtn = loanForm.querySelector("button");
  const tooYoung = eligible.length === 0;
  loanInput.disabled = tooYoung;
  loanBtn.disabled = tooYoung;
}

function setupFinanceTabs() {
  $$(".finances-area .tab").forEach((t) => {
    t.onclick = () => {
      $$(".finances-area .tab").forEach((x) => x.classList.remove("active"));
      t.classList.add("active");
      $("#tab-investments").classList.toggle("hidden", t.dataset.tab !== "investments");
      $("#tab-loans").classList.toggle("hidden", t.dataset.tab !== "loans");
      $opt("#tab-spend")?.classList.toggle("hidden", t.dataset.tab !== "spend");
      // Refresh purchases when the user opens the Spend tab — eligibility
      // depends on current state (subscriptions, money, age).
      if (t.dataset.tab === "spend") loadPurchases();
    };
  });

  $("#invest-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const productId = parseInt($("#invest-product").value, 10);
    const amount = parseInt($("#invest-amount").value, 10);
    const msg = $("#invest-msg");
    msg.textContent = "";
    try {
      await invest(productId, amount);
      $("#invest-amount").value = "";
    } catch (err) {
      msg.textContent = err.message.replace(/^\d+:\s*/, "");
    }
  });

  $("#loan-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const productId = parseInt($("#loan-product").value, 10);
    const amount = parseInt($("#loan-amount").value, 10);
    const msg = $("#loan-msg");
    msg.textContent = "";
    try {
      await takeLoan(productId, amount);
      $("#loan-amount").value = "";
    } catch (err) {
      msg.textContent = err.message.replace(/^\d+:\s*/, "");
    }
  });
}

// ---------- Country picker ----------
const REGION_ORDER = ["All", "Africa", "Americas", "Asia", "Europe", "Oceania"];

// Coarse continent buckets in seed.py separate "North America", "South
// America", "Central America", and "Caribbean" — for the picker filter
// we collapse all four into a single "Americas" tab to keep the UI tidy.
function regionBucket(region) {
  if (["North America", "South America", "Central America", "Caribbean"].includes(region)) {
    return "Americas";
  }
  return region;
}

const pickerState = {
  search: "",
  region: "All",
};

function renderCountryGrid() {
  const grid = $("#country-grid");
  grid.innerHTML = "";
  const q = pickerState.search.trim().toLowerCase();
  const filtered = state.countries
    .filter((c) => pickerState.region === "All" || regionBucket(c.region) === pickerState.region)
    .filter((c) => !q || c.name.toLowerCase().includes(q) || c.code === q)
    .sort((a, b) => a.name.localeCompare(b.name));
  if (filtered.length === 0) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No countries match your filter.";
    grid.appendChild(empty);
    return;
  }
  for (const c of filtered) {
    const tile = document.createElement("button");
    tile.className = "country-tile";
    tile.innerHTML = `<img src="/flags/${c.code}.bmp" alt=""><span>${c.name}</span>`;
    if (c.description) tile.title = c.description;
    tile.onclick = () => newGame(c.code);
    grid.appendChild(tile);
  }
}

function setupCountryPicker() {
  // Inject search input + region tabs above the grid (#33).
  const grid = $("#country-grid");
  const wrap = document.createElement("div");
  wrap.className = "picker-controls";
  wrap.innerHTML = `
    <input type="search" id="picker-search" placeholder="Search 199 countries…" autocomplete="off" />
    <div class="region-tabs" id="region-tabs"></div>
  `;
  grid.parentNode.insertBefore(wrap, grid);

  const tabs = $("#region-tabs");
  for (const r of REGION_ORDER) {
    const btn = document.createElement("button");
    btn.className = "region-tab" + (r === "All" ? " active" : "");
    btn.textContent = r;
    btn.dataset.region = r;
    btn.onclick = () => {
      pickerState.region = r;
      $$(".region-tab").forEach((t) => t.classList.toggle("active", t.dataset.region === r));
      renderCountryGrid();
    };
    tabs.appendChild(btn);
  }

  $("#picker-search").addEventListener("input", (e) => {
    pickerState.search = e.target.value;
    renderCountryGrid();
  });
}

// ---------- Bootstrapping ----------
async function init() {
  log("init: wiring event listeners");
  $("#btn-advance").addEventListener("click", advanceYear);
  $("#start-random").addEventListener("click", () => newGame(null));
  $("#btn-new").addEventListener("click", () => showStartScreen());
  $("#btn-restart").addEventListener("click", () => {
    // If we're viewing an archived life, "Live a new life" routes
    // back to the statistics screen instead of bouncing to the slot
    // picker — that'd be confusing and lose the player's place.
    if (_viewingArchivedLife) {
      _viewingArchivedLife = false;
      _viewingArchiveId = null;
      _viewingIsFavorite = false;
      $("#btn-back-to-stats").classList.add("hidden");
      $("#btn-toggle-favorite").classList.add("hidden");
      showStatisticsScreen();
    } else {
      showStartScreen();
    }
  });
  $("#btn-back-to-slots").addEventListener("click", backToSlotPicker);
  $("#btn-quit-job").addEventListener("click", quitJob);
  $("#btn-drop-out").addEventListener("click", dropOutOfSchool);
  $("#btn-enroll-uni").addEventListener("click", enrollUniversity);
  $opt("#btn-try-child")?.addEventListener("click", tryForChild);
  $("#btn-find-work").addEventListener("click", openJobBoard);
  $("#btn-jobboard-close").addEventListener("click", closeJobBoard);
  // #49: emigration
  $("#btn-emigrate").addEventListener("click", openEmigrationPicker);
  $("#btn-emigration-close").addEventListener("click", closeEmigrationPicker);
  $("#jobboard-show-all").addEventListener("change", (e) => {
    jobboardState.show_all = e.target.checked;
    renderJobBoardList();
  });
  // #70: statistics dashboard wiring
  $("#btn-statistics").addEventListener("click", showStatisticsScreen);
  $("#btn-stats-back").addEventListener("click", () => {
    // Return to wherever the player came from. If they came from a
    // game, that's the game; if from the start screen, slot picker.
    if (state.game && state.game.character && state.game.character.alive) {
      showGameScreen();
    } else {
      showStartScreen();
    }
  });
  $("#btn-back-to-stats").addEventListener("click", () => {
    _viewingArchivedLife = false;
    _viewingArchiveId = null;
    _viewingIsFavorite = false;
    $("#btn-back-to-stats").classList.add("hidden");
    $("#btn-toggle-favorite").classList.add("hidden");
    showStatisticsScreen();
  });
  $("#btn-toggle-favorite").addEventListener("click", toggleFavorite);
  $("#stats-import-btn").addEventListener("click", importArchive);
  $("#stats-import-input").addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    if (file) handleArchiveImport(file);
    e.target.value = "";  // allow re-importing the same file
  });
  $("#stats-clear-btn").addEventListener("click", clearNonFavorites);
  // #86: country map toggle. Persists in localStorage so the user
  // doesn't have to re-toggle on every dashboard open.
  const countryToggle = $opt("#stats-country-toggle");
  if (countryToggle) {
    const apply = (view) => {
      const table = $("#stats-country");
      const map = $("#stats-country-map");
      if (view === "map") {
        table.classList.add("hidden");
        map.classList.remove("hidden");
        countryToggle.textContent = "View as table";
        countryToggle.dataset.view = "map";
      } else {
        table.classList.remove("hidden");
        map.classList.add("hidden");
        countryToggle.textContent = "View as map";
        countryToggle.dataset.view = "table";
      }
      try { localStorage.setItem("rl_country_view", view); } catch {}
    };
    apply(localStorage.getItem("rl_country_view") || "table");
    countryToggle.addEventListener("click", () => {
      apply(countryToggle.dataset.view === "map" ? "table" : "map");
    });
  }
  // #88: filter form toggle.
  const filtersToggle = $opt("#stats-filters-toggle");
  if (filtersToggle) {
    filtersToggle.addEventListener("click", () => {
      const host = $opt("#stats-filters");
      if (host) host.classList.toggle("hidden");
    });
  }
  // #111: profile dropdown + management. Populated from /api/players
  // with "New Profile..." option. Rename/delete buttons manage profiles.
  $opt("#btn-rename-profile")?.addEventListener("click", renameProfile);
  $opt("#btn-delete-profile")?.addEventListener("click", deleteProfile);
  await loadProfileDropdown();
  log("init: loading countries + finance products");
  await loadCountries();
  await loadFinanceProducts();
  log(`init: loaded ${state.countries.length} countries, ${state.investmentProducts.length} investments, ${state.loanProducts.length} loans`);
  setupCountryPicker();
  renderCountryGrid();
  setupFinanceTabs();
  // Initial slot fetch + render. showStartScreen also does this, but
  // doing it once during init means the cards are already painted by
  // the time the user sees them on first load.
  await loadSlots();
  renderSlotGrid();
  log("init: ready");
}

init().catch((e) => {
  logErr("init failed", e);
  // Init failures are fatal — surface them in a real dialog so the user
  // sees an actionable error rather than a blank page.
  showAlert({
    title: "Failed to load",
    body: e.message,
    kind: "danger",
    confirmText: "Reload",
  }).then(() => window.location.reload());
});
