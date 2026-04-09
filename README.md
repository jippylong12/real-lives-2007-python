# real-lives-2007-python

A clean-room rebuild of **Real Lives 2007** as a modern open-source web
application. Born somewhere on Earth, weighted by population. Live one year
per turn. The country you wake up in determines your starting health,
education, life expectancy, the events you face, and the choices you'll be
given.

> *Real Lives* (Educational Simulations, 2007) was a Windows desktop life
> simulator that used real-world statistical data to model what life is like
> in countries most Western players had never visited. The original is
> abandonware. This rebuild is open source, runs in your browser, and is
> faithful to the original game's mechanics — not its assets.

## How this fits the three-repo project

This is the third stage of a three-stage rebuild. Each repo plays a different
role:

```
real-lives-2007-archive/    ← raw Ghidra output, original .dat assets, the binary
        │
        ▼
real-lives-2007-decompiled/ ← cleaned, named, organized pseudocode
        │
        ▼
real-lives-2007-python/     ← THIS REPO: runnable web rebuild
```

| Repo | What it is | Status |
|------|-----------|--------|
| [`real-lives-2007-archive`](../real-lives-2007-archive)        | Raw Ghidra-decompiled `.txt` for every recovered function, plus the original `.dat` files, flag images, tile maps, and the user guide PDF. Don't read it directly. | reference |
| [`real-lives-2007-decompiled`](../real-lives-2007-decompiled)  | The same functions, but renamed, annotated, and grouped by subsystem so you can browse them. The primary specification this rebuild is written against. | reference |
| **`real-lives-2007-python`** *(this repo)* | A FastAPI + SQLite + vanilla-JS rebuild of the game. The active development target. | runnable |

When porting a mechanic from the original, the workflow is:

1. Find the relevant function under `real-lives-2007-decompiled/<category>/`.
2. Read the header comment for the inferred purpose.
3. Cross-reference with the original raw Ghidra output if you need ground truth.
4. Implement the equivalent in idiomatic Python under `src/engine/`.

## Tech stack

- **Backend** — Python 3.11+, [FastAPI](https://fastapi.tiangolo.com/),
  Pydantic v2, SQLite (stdlib).
- **Frontend** — plain HTML / CSS / vanilla JavaScript. No framework, no build
  step. Editorial / magazine-style aesthetic.
- **Data** — the original game's `world.dat`, `jobs.dat`, `Investments.dat`,
  and `Loans.dat` files are bundled in `data/`. A custom parser
  (`src/data/parse_dat.py`) reads them; see *Data parsing* below.

## Download

Pre-built binaries are attached to each [GitHub
release](https://github.com/jippylong12/real-lives-2007-python/releases).
The build runs automatically on `macos-latest` (Apple Silicon), `macos-13`
(Intel), `windows-latest`, and `ubuntu-latest` whenever a `v*` tag is
pushed.

| Platform | Asset | What you get |
|---|---|---|
| macOS Apple Silicon (M1+) | `RealLives2007-<ver>-macos-arm64.zip` | `Real Lives 2007.app` bundle |
| macOS Intel | `RealLives2007-<ver>-macos-x86_64.zip` | `Real Lives 2007.app` bundle |
| Windows 10/11 (64-bit) | `RealLives2007-<ver>-windows-x86_64.zip` | folder with `RealLives2007.exe` |
| Linux x86_64 | `RealLives2007-<ver>-linux-x86_64.tar.gz` | folder with `RealLives2007` binary |

### macOS

1. Download the appropriate `.zip`, unzip — you get **Real Lives 2007.app**.
2. Drag it to `/Applications` (optional) and double-click to launch.
3. **First launch only**: Gatekeeper blocks unsigned apps. Right-click →
   **Open** → **Open**. Subsequent launches work normally.

The app saves games to `~/Library/Application Support/RealLives2007/`.

### Windows

1. Download the `.zip`, extract somewhere, and double-click `RealLives2007.exe`.
2. **First launch only**: Windows SmartScreen blocks unsigned apps with
   "Windows protected your PC". Click **More info** → **Run anyway**.

The app saves games to `%APPDATA%\RealLives2007\`.

### Linux

```bash
tar -xzf RealLives2007-<ver>-linux-x86_64.tar.gz
./RealLives2007/RealLives2007
```

Save games go to `$XDG_DATA_HOME/RealLives2007` (or `~/.local/share/RealLives2007`).

> All platforms ship unsigned. Code signing for Mac and Windows costs
> money and isn't worth it for a hobby project. PRs welcome from anyone
> with an Apple Developer ID or Windows code-signing cert.

## Run from source

```bash
git clone <this-repo>
cd real-lives-2007-python

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python src/main.py            # builds data/reallives.db on first run
                              # then serves http://127.0.0.1:8000
```

Open <http://127.0.0.1:8000> in a browser. Pick a country (or "start a random
life"), click *Live another year*, and play.

### Useful flags

```bash
python src/main.py --port 9000          # use a different port
python src/main.py --rebuild-db         # wipe and re-seed data/reallives.db
```

### Build the macOS .app yourself

```bash
bash packaging/build_macos.sh           # produces dist/Real Lives 2007.app
                                        #          dist/RealLives2007-<ver>-macos-<arch>.zip
```

The build script installs PyInstaller into the existing `.venv` if missing,
then runs the spec at `packaging/RealLives2007.spec`. Output is a 30-40MB
self-contained bundle containing Python, FastAPI, uvicorn, the original game's
`.dat` files, the frontend assets, and the launcher script.

## Project layout

```
real-lives-2007-python/
├── src/
│   ├── main.py                   # `python src/main.py` entry point
│   ├── engine/                   # game logic (no web concerns)
│   │   ├── character.py          # 12 attributes, birth, name pools
│   │   ├── world.py              # country lookup + weighted random birth
│   │   ├── death.py              # infant + background + old-age mortality
│   │   ├── events.py             # event registry, rolls, choice events
│   │   ├── education.py          # primary → secondary → university
│   │   ├── careers.py            # job assignment, salary scaling
│   │   ├── relationships.py      # marriage, family, children
│   │   ├── finances.py           # loans, investments, debt interest
│   │   └── game.py               # turn loop, save/load, decisions
│   ├── api/
│   │   └── app.py                # FastAPI routes
│   ├── data/
│   │   ├── parse_dat.py          # binary .dat schema extractor
│   │   ├── seed.py               # curated real-world country/job/loan data
│   │   └── build_db.py           # builds data/reallives.db
│   └── frontend/
│       ├── index.html            # SPA shell
│       ├── style.css             # editorial-style stylesheet
│       └── app.js                # vanilla JS UI
├── data/
│   ├── world.dat / world.idx     # original game world data
│   ├── jobs.dat / jobs.idx       # original game job catalogue
│   ├── Investments.dat / .idx    # original investment products
│   ├── Loans.dat / .idx          # original loan products
│   ├── flags/                    # 200+ country flag BMPs
│   ├── Real Lives Users Guide.pdf
│   └── reallives.db              # built on first run
├── tests/
│   ├── test_data.py              # parser + DB build tests
│   ├── test_engine.py            # birth, death, events, save/load
│   └── test_api.py               # FastAPI end-to-end
├── requirements.txt
└── README.md
```

## Game mechanics implemented

| Subsystem | Status | Notes |
|-----------|--------|-------|
| **Character** | ✅ | All 12 attributes (health, happiness, intelligence, artistic, musical, athletic, strength, endurance, appearance, conscience, wisdom, resistance) — see `src/engine/character.py`. |
| **Birth** | ✅ | Country chosen by population-weighted random; family wealth sampled from country GDP × Gini; starting attributes modulated by HDI / health services / literacy / safe-water access. |
| **Yearly turn loop** | ✅ | Education → job → income → debt → relationships → events → death roll. Implemented in `src/engine/game.py::Game.advance_year`. |
| **Death** | ✅ | Three-tier mortality: infant (per-1000), background (health-modulated), old-age (exponential ramp past country life expectancy). |
| **Events** | ✅ | 20 event types across health, crime, war, disaster, education, moral, finance, life. Both passive and player-choice events. New events drop into `EVENT_REGISTRY`. |
| **Education** | ✅ | Primary (age 6) → secondary → vocational/university. Intelligence and country literacy gate progression. |
| **Careers** | ✅ | 30 jobs with min education / intelligence / age requirements. Salary scales with country GDP. |
| **Relationships** | ✅ | Country-specific marriage age curves, spouse generation, financial merger. |
| **Finances** | ✅ | Yearly net income, debt accrual at 8% APR, financial-stress happiness penalty. Loan and investment products are seeded but UI for taking them is minimal. |
| **Save/load** | ✅ | Game state JSON-serialized into the `games` SQLite table. RNG state is checkpointed for reproducibility. |
| **Frontend** | ✅ | Dashboard, country picker, year-by-year event log, decision prompts, life timeline, death screen. |

### What is **not** yet implemented

- **Detailed disease model.** The original game tracks 50+ specific diseases
  individually (16 cancer types, staged syphilis, 10+ chlamydia complications;
  see `real-lives-2007-decompiled/FUN_FACT.md`). The rebuild collapses these
  into generic "serious illness" / "minor injury" events.
- **Investment / loan UI.** The products are seeded in the DB and exposed by
  the engine, but the frontend doesn't yet have a "manage finances" pane.
- **City-level granularity.** Original game places characters in specific
  named cities with city-specific risks. We currently always use the country
  capital.
- **Encyclopedia text.** The original game shows multi-paragraph
  Encarta/Worldbook summaries for each country. Out of scope for this stage.
- **Religion / cultural events.** The decompiled `events/moral/` and
  `world/culture/` folders contain rich religion-specific events; only a
  small subset are wired in.

## Data parsing

The original game's `.dat` files are Borland Delphi serialized records (a
BDE/Paradox-derived format). Each file is a 0x200-byte header followed by
0x300-byte records: the first N records are *schema records* (one per column,
with a length-prefixed Pascal field name), and subsequent records contain
Delphi tag-stream value blobs encoding extended-precision floats and dynamic
arrays.

`src/data/parse_dat.py` reliably extracts:

1. **The complete field schema** for `world.dat`, `jobs.dat`,
   `Investments.dat`, `Loans.dat` (169, 32, 6, and 7 fields respectively).
2. **Embedded ASCII strings** from the data records (job names, country
   names, city names, currency names, etc.).

The recovered schema is mirrored into the `dat_schema` SQLite table so the
rebuild's column set is provably anchored to the original game's columns.

**What is *not* recovered.** Numeric values (population, GDP, life
expectancy, etc.) live inside Delphi's 80-bit extended-precision float
encoding inside the value blobs, and reverse-engineering that fully is out
of scope. Instead, `src/data/seed.py` ships curated real-world stats for ~60
countries — sourced from the same kinds of public datasets the original game
used in 2007 (CIA World Factbook, World Bank, UNICEF, UNDP). Adding more
countries is just adding rows to that file.

## Tests

```bash
python3 -m pytest tests/ -q
```

All 19 tests should pass:

```
tests/test_api.py     ........
tests/test_data.py    ....
tests/test_engine.py  ........
```

The tests cover:
- `.dat` parsing (schema extraction + recovered string spot-checks)
- Database build (`reallives.db` table creation, country count)
- Character birth (attribute bounds, country effects)
- Death probability (infant / old-age curves)
- Event registry (well-formedness, country sensitivity)
- Game lifecycle (advance, save/load round-trip)
- API (health, country list, full new→advance→decide→get flow)

## Contributing

Contributions are very welcome. Things that would help most right now:

1. **More events.** Drop new entries into `EVENT_REGISTRY` in
   `src/engine/events.py`. The decompiled folder has hundreds of original
   events to port — pick one, port it.
2. **More countries.** Expand `src/data/seed.py::COUNTRIES` toward full
   global coverage.
3. **Better disease modeling.** Replace the generic illness event with the
   richer disease tracking from the original (see `events/health/` in the
   decompiled repo).
4. **Investment / loan UI.** The engine supports them; only the frontend
   pane is missing.
5. **Bring back encyclopedia text.** Each country could surface a
   real-world summary on the country picker.

Please open issues for discussion before sweeping refactors.

## Legal

The original *Real Lives 2007* was developed by Educational Simulations.
This project is a **clean-room reimplementation** of the game's mechanics,
written from scratch in Python against an annotated decompilation of the
original binary's logic. The rebuild does not include the original binary,
the original source code, or any copyrighted assets such as graphics, music,
or text strings.

The original `.dat` and flag image files bundled in `data/` are factual
statistical data and public-domain national symbols, respectively. They are
included so that the parser tests have something to assert against and so
that real flags appear in the UI. If a rights-holder objects to this use,
please open an issue.

This project is released under the MIT License (see [`LICENSE`](LICENSE)).
