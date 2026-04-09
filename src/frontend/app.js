/* Real Lives 2007 — vanilla JS frontend
 * Single-file SPA. Talks to /api/* endpoints exposed by FastAPI.
 */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const state = {
  game: null,
  countries: [],
  investmentProducts: [],
  loanProducts: [],
};

// ---------- API ----------
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
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

async function newGame(countryCode) {
  const body = countryCode ? { country_code: countryCode } : {};
  state.game = await api("/api/game/new", {
    method: "POST",
    body: JSON.stringify(body),
  });
  showGameScreen();
  renderGame();
}

async function advanceYear() {
  if (!state.game) return;
  const res = await api(`/api/game/${state.game.id}/advance`, { method: "POST" });
  state.game = res.game;
  renderGame();
  renderTurn(res.turn);
  if (res.turn.died) showDeathScreen(res.turn);
}

async function decide(choiceKey) {
  if (!state.game) return;
  const res = await api(`/api/game/${state.game.id}/decision`, {
    method: "POST",
    body: JSON.stringify({ choice_key: choiceKey }),
  });
  state.game = res.game;
  renderGame();
  renderTurn(res.turn);
}

// ---------- Rendering ----------
function showGameScreen() {
  $("#screen-start").classList.add("hidden");
  $("#screen-death").classList.add("hidden");
  $("#screen-game").classList.remove("hidden");
}

function showStartScreen() {
  $("#screen-game").classList.add("hidden");
  $("#screen-death").classList.add("hidden");
  $("#screen-start").classList.remove("hidden");
}

function showDeathScreen(turn) {
  $("#screen-game").classList.add("hidden");
  $("#screen-death").classList.remove("hidden");
  const c = state.game.character;
  $("#death-detail").textContent =
    `${c.name} died at age ${c.age} in ${c.city}, ${state.game.country.name}. Cause: ${turn.cause_of_death}.`;
  const tl = $("#death-timeline");
  tl.innerHTML = "";
  for (const line of c.history.slice(-25)) {
    const li = document.createElement("li");
    li.textContent = line;
    tl.appendChild(li);
  }
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
  $("#stat-salary").textContent = c.salary ? fmtMoney(c.salary) + "/yr" : "—";
  $("#stat-money").textContent = fmtMoney(c.money);
  $("#stat-portfolio").textContent = fmtMoney(g.portfolio_value || 0);
  $("#stat-debt").textContent = fmtMoney(c.debt || 0);
  $("#stat-married").textContent = c.married ? (c.spouse_name || "yes") : "no";
  $("#stat-kids").textContent = (c.children || []).length;
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

    const dh = facts.disaster_history || {};
    const dhSig = Object.entries(dh).filter(([, v]) => typeof v === "number" && v > 0);
    if (dhSig.length) {
      const h = document.createElement("h5");
      h.className = "facts-heading";
      h.textContent = "Disaster history (2007)";
      ci.appendChild(h);
      const ul = document.createElement("ul");
      ul.className = "facts-list";
      const labelMap = {
        EarthquakeAffected: "Earthquake-affected",
        EarthquakeKilled: "Earthquake deaths",
        FamineKilled: "Famine deaths",
        FamineAffected: "Famine-affected",
        FloodKilled: "Flood deaths",
        FloodAffected: "Flood-affected",
        DroughtKilled: "Drought deaths",
        DroughtAffected: "Drought-affected",
        EpidemicKilled: "Epidemic deaths",
        EpidemicAffected: "Epidemic-affected",
        AvalancheEvents: "Avalanche events",
        AvalancheAffected: "Avalanche-affected",
      };
      // Top 5 by magnitude.
      dhSig.sort(([, a], [, b]) => b - a);
      for (const [k, v] of dhSig.slice(0, 5)) {
        const li = document.createElement("li");
        li.textContent = `${labelMap[k] || k}: ${Math.round(v).toLocaleString()}`;
        ul.appendChild(li);
      }
      ci.appendChild(ul);
    }
  }

  // Year title
  $("#year-title").textContent = `Age ${c.age} · Year ${g.year}`;

  // Timeline
  const tl = $("#timeline");
  tl.innerHTML = "";
  for (const line of c.history.slice(-50).reverse()) {
    const li = document.createElement("li");
    li.textContent = line;
    tl.appendChild(li);
  }

  // Pending decision
  const dArea = $("#decision-area");
  if (g.pending_event) {
    dArea.classList.remove("hidden");
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
    dArea.classList.add("hidden");
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
    node.className = `event ${ev.category}`;
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
      <div>${ev.summary}</div>
      ${deltas ? `<div style="margin-top:6px">${deltas}</div>` : ""}
    `;
    list.appendChild(node);
  }
}

// ---------- Finances pane ----------
function renderFinances() {
  const c = state.game?.character;
  if (!c) return;

  // Open investments list
  const invHost = $("#open-investments");
  invHost.innerHTML = "";
  const invs = c.investments || [];
  if (invs.length === 0) {
    invHost.innerHTML = '<p class="placeholder">No open investments.</p>';
  } else {
    invs.forEach((inv, i) => {
      const pl = inv.value - inv.cost_basis;
      const cls = pl >= 0 ? "up" : "down";
      const row = document.createElement("div");
      row.className = "holding";
      row.innerHTML = `
        <div class="h-name">${inv.name}</div>
        <div class="h-meta">cost ${fmtMoney(inv.cost_basis)} · value <strong>${fmtMoney(inv.value)}</strong>
          <span class="delta ${cls}">${pl >= 0 ? "+" : ""}${fmtMoney(pl)}</span></div>
        <button class="btn sm" data-sell="${i}">Sell</button>`;
      invHost.appendChild(row);
    });
    invHost.querySelectorAll("[data-sell]").forEach((b) => {
      b.onclick = () => sellInvestment(parseInt(b.dataset.sell, 10));
    });
  }

  // Investment product dropdown
  const invSel = $("#invest-product");
  if (invSel.options.length !== state.investmentProducts.length) {
    invSel.innerHTML = "";
    for (const p of state.investmentProducts) {
      const opt = document.createElement("option");
      opt.value = p.id;
      const lo = (p.annual_return_low * 100).toFixed(0);
      const hi = (p.annual_return_high * 100).toFixed(0);
      opt.textContent = `${p.name} (${lo}% – ${hi}% / yr, min ${fmtMoney(p.min_amount)})`;
      invSel.appendChild(opt);
    }
  }

  // Open loans list
  const loanHost = $("#open-loans");
  loanHost.innerHTML = "";
  const loans = c.loans || [];
  if (loans.length === 0) {
    loanHost.innerHTML = '<p class="placeholder">No open loans.</p>';
  } else {
    loans.forEach((l) => {
      const row = document.createElement("div");
      row.className = "holding";
      row.innerHTML = `
        <div class="h-name">${l.name}</div>
        <div class="h-meta">balance <strong>${fmtMoney(l.balance)}</strong>
          · ${(l.interest_rate * 100).toFixed(1)}% APR
          · ${l.years_remaining} yrs left</div>`;
      loanHost.appendChild(row);
    });
  }

  // Loan product dropdown
  const loanSel = $("#loan-product");
  if (loanSel.options.length !== state.loanProducts.length) {
    loanSel.innerHTML = "";
    for (const p of state.loanProducts) {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = `${p.name} (max ${fmtMoney(p.max_amount)}, ${(p.interest_rate * 100).toFixed(0)}% / ${p.max_years} yrs)`;
      loanSel.appendChild(opt);
    }
  }
}

function setupFinanceTabs() {
  $$(".finances-area .tab").forEach((t) => {
    t.onclick = () => {
      $$(".finances-area .tab").forEach((x) => x.classList.remove("active"));
      t.classList.add("active");
      $("#tab-investments").classList.toggle("hidden", t.dataset.tab !== "investments");
      $("#tab-loans").classList.toggle("hidden", t.dataset.tab !== "loans");
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
function renderCountryGrid() {
  const grid = $("#country-grid");
  grid.innerHTML = "";
  const sorted = [...state.countries].sort((a, b) => a.name.localeCompare(b.name));
  for (const c of sorted) {
    const tile = document.createElement("button");
    tile.className = "country-tile";
    tile.innerHTML = `<img src="/flags/${c.code}.bmp" alt=""><span>${c.name}</span>`;
    if (c.description) tile.title = c.description;
    tile.onclick = () => newGame(c.code);
    grid.appendChild(tile);
  }
}

// ---------- Bootstrapping ----------
async function init() {
  $("#btn-advance").addEventListener("click", advanceYear);
  $("#start-random").addEventListener("click", () => newGame(null));
  $("#btn-new").addEventListener("click", () => showStartScreen());
  $("#btn-restart").addEventListener("click", () => showStartScreen());
  await loadCountries();
  await loadFinanceProducts();
  renderCountryGrid();
  setupFinanceTabs();
}

init().catch((e) => {
  console.error(e);
  alert("Failed to load: " + e.message);
});
