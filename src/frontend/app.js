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

async function payLoan(index, amount) {
  state.game = await api(`/api/game/${state.game.id}/pay_loan`, {
    method: "POST",
    body: JSON.stringify({ index, amount }),
  });
  renderGame();
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

// ---------- Job board (#54) ----------
const jobboardState = {
  category: "All",
  listings: [],
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
  // Sort: qualified > stretch > long_shot > out_of_reach, then salary desc.
  const statusOrder = { qualified: 0, stretch: 1, long_shot: 2, out_of_reach: 3 };
  listings = [...listings].sort((a, b) => {
    const so = statusOrder[a.status] - statusOrder[b.status];
    return so !== 0 ? so : b.expected_salary - a.expected_salary;
  });
  if (listings.length === 0) {
    host.innerHTML = '<p class="muted">No jobs in this category.</p>';
    return;
  }
  for (const l of listings) {
    const row = document.createElement("div");
    row.className = `jobboard-row status-${l.status}`;
    const chancePct = Math.round(l.accept_chance * 100);
    const missing = l.missing.length ? `<div class="jr-missing">${l.missing.join(" · ")}</div>` : "";
    row.innerHTML = `
      <div class="jr-main">
        <div class="jr-name">${l.name}</div>
        <div class="jr-meta">${l.category || "—"} · ${fmtMoney(l.expected_salary)}/yr</div>
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
  if (!confirm("Ask for a raise or promotion? You could get one — or you could be let go.")) return;
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

async function newGame(countryCode) {
  log(`newGame(${countryCode || "random"})`);
  try {
    const body = countryCode ? { country_code: countryCode } : {};
    state.game = await api("/api/game/new", {
      method: "POST",
      body: JSON.stringify(body),
    });
    log(`new game created: ${state.game.id} — ${state.game.character.name} in ${state.game.country.name}`);
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

function showStartScreen() {
  $("#screen-game").classList.add("hidden");
  $("#screen-death").classList.add("hidden");
  $("#screen-start").classList.remove("hidden");
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
      const askBtn = career.can_request_raise
        ? `<button id="btn-ask-raise" class="btn xs">Ask for raise</button>`
        : (career.years_in_role >= career.years_to_promote
            ? `<button class="btn xs" disabled title="${career.raise_blocked_reason || ""}">Ask for raise</button>`
            : "");
      careerEl.innerHTML = `
        <div class="career-head">
          <span class="career-cat">${cat}</span>
          <span class="career-promos">${career.promotion_count} promotion${career.promotion_count === 1 ? "" : "s"}</span>
        </div>
        <div class="career-bar"><span style="width:${ladderProgress}%"></span></div>
        <div class="career-yrs">${career.years_in_role} / ${career.years_to_promote} yrs in role ${askBtn}</div>
        ${nextLine}
      `;
      const btn = $opt("#btn-ask-raise");
      if (btn) btn.addEventListener("click", requestRaise);
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

  // Timeline
  const tl = $("#timeline");
  tl.innerHTML = "";
  for (const line of c.history.slice(-50).reverse()) {
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

  // Open loans list with manual repay control (#40).
  const loanHost = $("#open-loans");
  loanHost.innerHTML = "";
  const loans = c.loans || [];
  if (loans.length === 0) {
    loanHost.innerHTML = '<p class="placeholder">No open loans.</p>';
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
  $("#btn-quit-job").addEventListener("click", quitJob);
  $("#btn-find-work").addEventListener("click", openJobBoard);
  $("#btn-jobboard-close").addEventListener("click", closeJobBoard);
  log("init: loading countries + finance products");
  await loadCountries();
  await loadFinanceProducts();
  log(`init: loaded ${state.countries.length} countries, ${state.investmentProducts.length} investments, ${state.loanProducts.length} loans`);
  setupCountryPicker();
  renderCountryGrid();
  setupFinanceTabs();
  log("init: ready");
}

init().catch((e) => {
  logErr("init failed", e);
  alert("Failed to load: " + e.message);
});
