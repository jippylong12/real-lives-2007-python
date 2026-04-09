/* Real Lives 2007 — vanilla JS frontend
 * Single-file SPA. Talks to /api/* endpoints exposed by FastAPI.
 */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const state = {
  game: null,
  countries: [],
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
  $("#char-where").textContent = `${c.city}, ${co.name}`;

  $("#stat-age").textContent = c.age;
  $("#stat-year").textContent = g.year;
  $("#stat-edu").textContent = EDU_LABELS[c.education] || "—";
  $("#stat-job").textContent = c.job || "—";
  $("#stat-salary").textContent = c.salary ? fmtMoney(c.salary) + "/yr" : "—";
  $("#stat-money").textContent = fmtMoney(c.money);
  $("#stat-married").textContent = c.married ? (c.spouse_name || "yes") : "no";
  $("#stat-kids").textContent = (c.children || []).length;

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

  // Country panel
  const ci = $("#country-info");
  ci.innerHTML = "";
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

// ---------- Country picker ----------
function renderCountryGrid() {
  const grid = $("#country-grid");
  grid.innerHTML = "";
  const sorted = [...state.countries].sort((a, b) => a.name.localeCompare(b.name));
  for (const c of sorted) {
    const tile = document.createElement("button");
    tile.className = "country-tile";
    tile.innerHTML = `<img src="/flags/${c.code}.bmp" alt=""><span>${c.name}</span>`;
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
  renderCountryGrid();
}

init().catch((e) => {
  console.error(e);
  alert("Failed to load: " + e.message);
});
