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

async function invest(productId, amount) {
  state.game = await api(`/api/game/${state.game.id}/invest`, {
    method: "POST",
    body: JSON.stringify({ product_id: productId, amount }),
  });
  renderGame();
}

async function takeLoan(productId, amount) {
  state.game = await api(`/api/game/${state.game.id}/loan`, {
    method: "POST",
    body: JSON.stringify({ product_id: productId, amount }),
  });
  renderGame();
}

async function sellInvestment(index) {
  state.game = await api(`/api/game/${state.game.id}/sell_investment`, {
    method: "POST",
    body: JSON.stringify({ index }),
  });
  renderGame();
}

async function payLoan(index, amount) {
  state.game = await api(`/api/game/${state.game.id}/pay_loan`, {
    method: "POST",
    body: JSON.stringify({ index, amount }),
  });
  renderGame();
}

// ---------- Spend (#66) ----------
const spendState = {
  category: "big",
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

  // Category tabs
  const tabsHost = $opt("#purchase-categories");
  const cats = ["big", "lifestyle", "subscription", "charity", "gift"];
  const labels = { big: "Big purchases", lifestyle: "Lifestyle", subscription: "Subscriptions", charity: "Charity", gift: "Gifts" };
  tabsHost.innerHTML = "";
  for (const cat of cats) {
    const btn = document.createElement("button");
    btn.className = "purchase-tab" + (cat === spendState.category ? " active" : "");
    btn.textContent = labels[cat];
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
      if (blocked) { alert(blocked); return; }
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

  row.innerHTML = `
    <div class="pr-main">
      <div class="pr-name">${p.name} ${ownedTag}</div>
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
  } catch (e) {
    logErr("cancelSubscription failed", e);
    alert(e.message);
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

  // Wire clicks. Blocked buttons just alert their reason. Live buttons
  // call the action.
  function wireAction(id, action) {
    const btn = $opt("#" + id);
    if (!btn) return;
    btn.addEventListener("click", () => {
      const blocked = btn.dataset.blocked;
      if (blocked) { alert(blocked); return; }
      action();
    });
  }
  wireAction("btn-checkup", buyCheckup);
  wireAction("btn-major", buyMajorTreatment);
  host.querySelectorAll("[data-treat-disease]").forEach((b) => {
    b.onclick = () => {
      const blocked = b.dataset.blocked;
      if (blocked) { alert(blocked); return; }
      treatDisease(b.dataset.treatDisease);
    };
  });
}

async function buyCheckup() {
  log("buyCheckup");
  try {
    const res = await api(`/api/game/${state.game.id}/buy_checkup`, { method: "POST" });
    state.game = res.game;
    alert(res.message);
    await loadHealthcare();
    renderGame();
  } catch (e) {
    logErr("buyCheckup failed", e);
    alert(e.message);
  }
}

async function buyMajorTreatment() {
  log("buyMajorTreatment");
  try {
    const res = await api(`/api/game/${state.game.id}/buy_major_treatment`, { method: "POST" });
    state.game = res.game;
    alert(res.message);
    await loadHealthcare();
    renderGame();
  } catch (e) {
    logErr("buyMajorTreatment failed", e);
    alert(e.message);
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
    alert(res.message);
    await loadHealthcare();
    renderGame();
  } catch (e) {
    logErr("treatDisease failed", e);
    alert(e.message);
  }
}

async function quitJob() {
  if (!confirm("Quit your current job? You'll need to find a new one.")) return;
  log("quitJob");
  try {
    state.game = await api(`/api/game/${state.game.id}/quit_job`, { method: "POST" });
    renderGame();
  } catch (e) {
    logErr("quitJob failed", e);
    alert(`Could not quit job: ${e.message}`);
  }
}

async function dropOutOfSchool() {
  if (!confirm("Drop out of school to start working? You can't go back.")) return;
  log("dropOutOfSchool");
  try {
    state.game = await api(`/api/game/${state.game.id}/drop_out_of_school`, { method: "POST" });
    renderGame();
    loadPurchases();
    loadHealthcare();
  } catch (e) {
    logErr("dropOutOfSchool failed", e);
    alert(`Could not drop out: ${e.message}`);
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

async function loadSlots() {
  try {
    slotState.slots = await api("/api/slots");
    log(`loaded ${slotState.slots.length} slots`);
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
    alert(`Could not load that game: ${e.message}`);
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
    alert(`Could not load the job board: ${e.message}`);
  }
}

function closeJobBoard() {
  $("#jobboard-modal").classList.add("hidden");
}

function renderJobBoardTabs() {
  const tabs = $("#jobboard-tabs");
  const cats = ["All", ...new Set(jobboardState.listings.map((l) => l.category).filter(Boolean))].sort((a, b) =>
    a === "All" ? -1 : b === "All" ? 1 : a.localeCompare(b)
  );
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
  if (jobboardState.category !== "All") {
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
    alert(`Apply failed: ${e.message}`);
  }
}

async function requestRaise() {
  if (!confirm("Ask for a salary raise? You could get one — or you could be let go.")) return;
  log("requestRaise");
  try {
    const res = await api(`/api/game/${state.game.id}/request_raise`, { method: "POST" });
    state.game = res.game;
    log(`raise outcome: ${res.outcome} — ${res.message}`);
    alert(res.message);
    renderGame();
  } catch (e) {
    logErr("requestRaise failed", e);
    alert(`Could not request raise: ${e.message}`);
  }
}

async function requestPromotion() {
  if (!confirm("Ask for a promotion? You could move up — or you could be let go.")) return;
  log("requestPromotion");
  try {
    const res = await api(`/api/game/${state.game.id}/request_promotion`, { method: "POST" });
    state.game = res.game;
    log(`promotion outcome: ${res.outcome} — ${res.message}`);
    alert(res.message);
    renderGame();
  } catch (e) {
    logErr("requestPromotion failed", e);
    alert(`Could not request promotion: ${e.message}`);
  }
}

async function newGame(countryCode) {
  // Always thread the currently-selected slot through (#79). The user
  // must have picked a slot before getting here — if not, fail loud.
  const slot = slotState.pendingSlot;
  if (slot == null) {
    log("newGame called without a pending slot — bailing");
    alert("Pick a save slot first.");
    backToSlotPicker();
    return;
  }
  log(`newGame(slot=${slot}, country=${countryCode || "random"})`);
  try {
    const body = { slot };
    if (countryCode) body.country_code = countryCode;
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
    alert(`Could not start a new life: ${e.message}`);
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
    renderGame();
    renderTurn(res.turn);
    if (res.turn.died) showDeathScreen(res.turn);
    // Refresh spending + healthcare panels (eligibility changes
    // every year as the character ages, gets new diseases, etc).
    loadPurchases();
    loadHealthcare();
  } catch (e) {
    logErr("advanceYear failed", e);
    alert(`Failed to advance year: ${e.message}`);
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
  } catch (e) {
    logErr("decide failed", e);
    alert(`Failed to apply decision: ${e.message}`);
  }
}

// ---------- Rendering ----------
function showGameScreen() {
  $("#screen-start").classList.add("hidden");
  $("#screen-death").classList.add("hidden");
  $("#screen-game").classList.remove("hidden");
}

async function showStartScreen() {
  $("#screen-game").classList.add("hidden");
  $("#screen-death").classList.add("hidden");
  $("#screen-start").classList.remove("hidden");
  // Always return to the slot picker view first; never leave the
  // user staring at a country grid when they came back from a life.
  backToSlotPicker();
  // Refresh slots from the server every time we show the start screen
  // so the cards reflect the latest state (the life we just exited
  // may have changed age / died this turn).
  await loadSlots();
  renderSlotGrid();
}

function showDeathScreen(turn) {
  $("#screen-game").classList.add("hidden");
  $("#screen-death").classList.remove("hidden");
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
    ["Married", c.married ? (c.spouse_name || "yes") : "no"],
    ["Children", numChildren],
    ["Diseases endured", `${numDiseases}${numChronics ? ` (${numChronics} chronic)` : ""}`],
    ["Top wisdom", c.attributes?.wisdom ?? 0],
    ["Top conscience", c.attributes?.conscience ?? 0],
  ];
  for (const [k, v] of stats) {
    const row = document.createElement("div");
    row.className = "ds-row";
    row.innerHTML = `<span>${k}</span><strong>${v}</strong>`;
    summary.appendChild(row);
  }

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
  const where = `${c.city}, ${co.name}`;
  $("#char-where").textContent = c.is_urban === false ? `${where} · rural` : where;

  $("#stat-age").textContent = c.age;
  $("#stat-year").textContent = g.year;
  $("#stat-edu").textContent = EDU_LABELS[c.education] || "—";
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
  $("#stat-salary").textContent = c.salary ? fmtMoney(c.salary) + "/yr" : "—";
  $("#stat-money").textContent = fmtMoney(c.money);
  $("#stat-portfolio").textContent = fmtMoney(g.portfolio_value || 0);
  $("#stat-debt").textContent = fmtMoney(c.debt || 0);
  $("#stat-married").textContent = c.married ? (c.spouse_name || "yes") : "no";
  $("#stat-kids").textContent = (c.children || []).length;

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
      let nextLine = "";
      if (career.next_job) {
        const ageGate = career.next_min_age && c.age < career.next_min_age ? `, age ${career.next_min_age}+` : "";
        const iqGate = career.next_min_intelligence > c.attributes.intelligence
          ? `, IQ ${career.next_min_intelligence}+` : "";
        nextLine = `<div class="career-next">Next: <strong>${career.next_job}</strong> (${career.years_to_promote} yrs in role${ageGate}${iqGate})</div>`;
      } else {
        nextLine = `<div class="career-next muted">Top of the ladder.</div>`;
      }
      const cat = career.vocation_field || career.category || "—";
      const eligibleByYears = career.years_in_role >= career.years_to_promote;

      // Two buttons (#63): salary raise and promotion. Each shows enabled
      // when can_request_*, disabled with tooltip when years_in_role
      // crosses the threshold but the gate is something else.
      let raiseBtn = "";
      if (career.can_request_raise) {
        raiseBtn = `<button id="btn-ask-raise" class="btn xs">Ask for raise</button>`;
      } else if (eligibleByYears) {
        raiseBtn = `<button class="btn xs" disabled title="${career.raise_blocked_reason || ""}">Ask for raise</button>`;
      }
      let promoBtn = "";
      if (career.can_request_promotion) {
        promoBtn = `<button id="btn-ask-promo" class="btn xs">Ask for promotion</button>`;
      } else if (eligibleByYears && career.next_job) {
        promoBtn = `<button class="btn xs" disabled title="${career.promotion_blocked_reason || ""}">Ask for promotion</button>`;
      }

      careerEl.innerHTML = `
        <div class="career-head">
          <span class="career-cat">${cat}</span>
          <span class="career-promos">${career.promotion_count} promotion${career.promotion_count === 1 ? "" : "s"}</span>
        </div>
        <div class="career-bar"><span style="width:${ladderProgress}%"></span></div>
        <div class="career-yrs">${career.years_in_role} / ${career.years_to_promote} yrs in role</div>
        ${nextLine}
        ${(raiseBtn || promoBtn) ? `<div class="career-actions">${raiseBtn} ${promoBtn}</div>` : ""}
      `;
      const rb = $opt("#btn-ask-raise");
      if (rb) rb.addEventListener("click", requestRaise);
      const pb = $opt("#btn-ask-promo");
      if (pb) pb.addEventListener("click", requestPromotion);
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
          alert(e.message);
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
  $("#btn-restart").addEventListener("click", () => showStartScreen());
  $("#btn-back-to-slots").addEventListener("click", backToSlotPicker);
  $("#btn-quit-job").addEventListener("click", quitJob);
  $("#btn-drop-out").addEventListener("click", dropOutOfSchool);
  $("#btn-find-work").addEventListener("click", openJobBoard);
  $("#btn-jobboard-close").addEventListener("click", closeJobBoard);
  $("#jobboard-show-all").addEventListener("change", (e) => {
    jobboardState.show_all = e.target.checked;
    renderJobBoardList();
  });
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
  alert("Failed to load: " + e.message);
});
