# Changelog

All notable changes to Real Lives 2007 (Python rebuild).

The format is [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.3.0] — 2026-04-09

Money matters now, and so does where you save your life. v1.3.0 turns
discretionary spending into a real game system, replaces the silent
auto-save model with five explicit save slots, adds pay-for-healthcare,
forces aged-out athletes to retire, and rewrites the job acceptance
heuristic so the job board produces a real spread of probabilities
instead of bimodal 80% / 25% cliffs.

Plus a clutch of UX fixes the user surfaced while playing: investment
clarity, treatment buttons that actually explain why they're disabled,
spend tab affordability checks, timeline grouping for repeated events,
and a finances panel that always shows useful info.

### Added

- **Discretionary spending registry** — 16 purchases across houses,
  cars, vacations, subscriptions, charity, and gifts. Each item has a
  country-scaled price, eligibility gates, and (for subscriptions) a
  yearly recurring cost that's deducted from income with named effect
  log entries every year
  ([#66](https://github.com/jippylong12/real-lives-2007-python/issues/66),
   [#76](https://github.com/jippylong12/real-lives-2007-python/issues/76),
   [#77](https://github.com/jippylong12/real-lives-2007-python/issues/77)).
- **Pay-for-healthcare** — Checkup, Major treatment, and per-disease
  cures sit under the health bar. Each action has a country-scaled
  cost, an age multiplier (full effect ≤60, falls to 0.2× by 90),
  and a country effectiveness scalar. Permanent diseases get
  *managed* (capped progression) instead of cured
  ([#67](https://github.com/jippylong12/real-lives-2007-python/issues/67)).
- **Save slot system (5 slots)** — start screen rebuilt as a 5-slot
  picker. Each slot holds one current life; clicking an empty/dead
  slot opens a country picker scoped to that slot. Multiple games
  can share a slot (history of dead lives), and `list_slots()`
  returns the most-recent game per slot. Replaces the old auto-save
  modal entirely. New `GET /api/slots` endpoint and `slot` param on
  `POST /api/game/new`. `games` table gains a `slot` column with an
  idempotent ALTER TABLE migration so existing saves survive
  ([#79](https://github.com/jippylong12/real-lives-2007-python/issues/79)).
- **Investment year-over-year delta** — `InvestmentHolding.last_year_delta`
  is tracked in `tick_finances`. Holdings now show two chips:
  lifetime P/L *and* "this yr" delta. Players can finally see the
  year-over-year change directly, instead of staring at a lifetime
  total that hovers near zero
  ([#74](https://github.com/jippylong12/real-lives-2007-python/issues/74)).
- **Auto-retirement at job's max_age** — `game.advance_year` checks
  if the character has aged past their job's `max_age` and forces
  retirement: job=None, salary=0, years_in_role=0. Athletes retire
  at 38-40, soldiers at 55, doctors at 80. `promotion_count` is
  preserved (you earned those promotions) but the seniority clock
  resets if you re-enter a career
  ([#75](https://github.com/jippylong12/real-lives-2007-python/issues/75)).
- **Drop out of school** button — visible when the character is in
  school AND has reached the country's minimum working age. Quitting
  school early sets `in_school = False` so the work-eligibility gate
  clears; the previous education level stays
  ([#69](https://github.com/jippylong12/real-lives-2007-python/issues/69)).
- **Investment age gates** — savings opens at 14, all other products
  at 18 (matches the loan age gate). Stops 5-year-olds from buying
  index funds
  ([#68](https://github.com/jippylong12/real-lives-2007-python/issues/68)).
- **Timeline grouping for repeated events** — `groupTimelineLines()`
  collapses runs of identical "Age N: text" entries into "Age N-M:
  text (Kx)". A 4-year Diwali streak now renders as one line
  instead of four
  ([#80](https://github.com/jippylong12/real-lives-2007-python/issues/80)).
- **Finances panel header summary** — Cash · Portfolio · Debt
  rendered inline on the collapsed panel summary so the panel is
  never empty space
  ([#81](https://github.com/jippylong12/real-lives-2007-python/issues/81)).

### Changed

- **Job acceptance heuristic — real probability spread**. The old
  logit was bimodal: every match slammed to ~80%, every miss to
  ~25%. Rewrite produces a smooth distribution across the 30-80%
  band. Sample for a 25yo university grad with IQ 89: 81% scavenger
  / 76% stall salesperson / 75% soldier / 71% secretary / 64%
  mineral processing operator / 51% marketing director / 47%
  software dept manager / 35% doctor / 30% elite athlete. Lowers
  the baseline (0.5 → -0.2), softens education / IQ / urban-rural
  / vocation penalties, adds a salary tier difficulty
  (`-log(salary_mid / 15_000) * 0.65`) so high-paying jobs are
  competitive even when minimums are met, and tightens the
  probability clamp from `[0.01, 0.95]` to `[0.03, 0.85]`. Status
  thresholds: qualified ≥60%, stretch 40-60%, long_shot 10-40%
  — the 40% line means the job board's default view (hide long
  shots) shows only realistic options.
- **Investment expected returns** bumped to real-world means.
  Low-risk stock fund averaged 2% before — well below the actual
  S&P 500 long-run ~7%. New means: savings 2.5%, gov bonds 4%,
  corp bonds 5%, low-risk stock fund 6.5%, high-risk fund 10%,
  real estate 6%
  ([#74](https://github.com/jippylong12/real-lives-2007-python/issues/74)).
- **Crude job minimum age** — prostitute and thief in `jobs.dat`
  ship with `min_age` 13 and 12. Override to 18 in `build_db.py`
  via `CRUDE_JOB_MIN_AGE_OVERRIDE` regardless of the binary value.
  Other low-min-age jobs (subsistence farmer, beggar, scavenger)
  keep their values since those reflect real economic conditions
  in low-HDI countries that the simulation models
  ([#78](https://github.com/jippylong12/real-lives-2007-python/issues/78)).
- **Healthcare action buttons** now use a `blocked` visual class
  + click-to-alert pattern instead of `disabled`. The button stays
  clickable, dims to 55% opacity, and pops an alert with the
  blocked reason on click. Touch devices have no tooltip equivalent
  for `disabled`-only buttons, so the user kept tapping "Major
  treatment" and getting nothing. Same pattern reused for the
  Spend tab Buy buttons
  ([#71](https://github.com/jippylong12/real-lives-2007-python/issues/71)).
- **Spend listing affordability check** — `spending.list_purchases`
  now returns an `affordable` flag rolled into `eligible`. Frontend
  disables Buy when the character can't actually pay. Stops the
  silent 400 the user hit when they tried to buy a $50k home with
  $5k cash
  ([#73](https://github.com/jippylong12/real-lives-2007-python/issues/73)).
- **Finances tab styling tightened** — smaller padding and font
  on the segmented control, better empty-state copy that explains
  the value proposition instead of just "no holdings"
  ([#81](https://github.com/jippylong12/real-lives-2007-python/issues/81)).

### Removed

- **Saved games modal** and topbar button. Replaced entirely by the
  slot picker on the start screen
  ([#79](https://github.com/jippylong12/real-lives-2007-python/issues/79)).
- **Auto-save indicator pulse** is still there for feedback, but it
  no longer drives a separate "Continue last life" button — the
  slot picker is the source of truth.

### Technical

- `games` table gains a `slot INTEGER` column. New `_migrate()` step
  in `get_connection()` runs an idempotent ALTER TABLE so existing
  DBs gain the column without a rebuild that would wipe state.
- `GameState.slot` round-trips through `to_dict` / `from_dict`.
  `Game.new(slot=...)` accepts an optional slot.
- `careers._accept_logit` redesigned around a wider sigmoid spread
  with a salary-tier difficulty modifier.
- New `careers._logit_to_probability` clamp [0.03, 0.85] (was
  [0.01, 0.95]).
- New `engine.spending` module — 16-purchase registry with
  ownership tracking, `buy()` function, `apply_subscription_effects()`
  returning records for the event log.
- New `engine.healthcare` module — `buy_checkup`, `buy_major_treatment`,
  `treat_disease` with age multiplier and country effectiveness.

### Test coverage

99 tests passing (was 87 in v1.2.0). New tests:

- `test_apply_for_job_mid_tier_is_stretch` — locks in the new
  acceptance spread by asserting that engineer for an over-qualified
  candidate lands in 35-70% (not 80%+).
- `test_apply_for_job_qualified_acceptance_high` updated to use
  `nursery school aid` (a true low-tier match) since engineer is
  intentionally no longer a slam-dunk under the new heuristic.
- Plus tests added throughout the v1.3 batch for spending, healthcare,
  retirement, drop-out, age gates, etc.

### Issues closed

15 issues closed since v1.2.0: #66, #67, #68, #69, #71, #72, #73, #74,
#75, #76, #77, #78, #79, #80, #81.

## [1.2.0] — 2026-04-09

Career system overhaul. The career loop in v1.1.0 was a single random
yearly job assignment with a flat promotion event — by v1.2.0 it's a
real career: 14 vocations with promotion ladders sourced from the
binary's `PromotesTo` field, attribute-driven progression speed, a
job board you can browse and apply to, freelance careers where talent
defines earnings, and a salary-raise / promotion request system with
real outcomes including being fired.

Plus realistic character attribute distributions so the world finally
has variety — most people are average with one or two clear talents
and weaknesses, instead of everyone being good at everything.

### Added

- **Vocation system** — 14 categories (medical, stem, education,
  government, police, military, arts, business, trades, industrial,
  agriculture, maritime, athletics, service) sourced from the binary's
  131 jobs plus 15 synthetic ladder rungs
  ([#51](https://github.com/jippylong12/real-lives-2007-python/issues/51),
   [#59](https://github.com/jippylong12/real-lives-2007-python/issues/59)).
- **Promotion ladders from `jobs.dat`** — the binary's `PromotesTo`
  field defines real career chains: police constable → inspector →
  captain → chief, seaman → second mate → first mate → ship's captain,
  engineer → engineering dept manager → general manager → company
  president, and so on
  ([#51](https://github.com/jippylong12/real-lives-2007-python/issues/51)).
- **Attribute-driven promotion speed and salary** — each category
  declares a relevant attribute. A high-IQ engineer climbs faster
  than a low-IQ one. Same role, salary scales 50-100% with the
  relevant attribute
  ([#60](https://github.com/jippylong12/real-lives-2007-python/issues/60)).
- **University major + vocational track choice** at age 18, picked
  via two new CHOICE events. The chosen field constrains future job
  assignments to that category
  ([#48](https://github.com/jippylong12/real-lives-2007-python/issues/48),
   [#51](https://github.com/jippylong12/real-lives-2007-python/issues/51)).
- **Job board** — `Find work` button opens a modal listing every
  job in the catalogue with the character's eligibility, predicted
  acceptance probability, missing requirements, and an Apply button.
  Always at least a 1% chance of acceptance, never higher than 95%
  ([#54](https://github.com/jippylong12/real-lives-2007-python/issues/54)).
- **Continuous acceptance probabilities** — the job board now shows
  a smooth spread of percentages (87, 86, 84, 83, 78, 76, 72, 60, 35,
  15, ...) instead of bucketed 80/30/10/3
  ([#64](https://github.com/jippylong12/real-lives-2007-python/issues/64)).
- **Hide long shots toggle** in the job board — only realistic
  options shown by default; toggle to see the full 131-job catalogue
  ([#58](https://github.com/jippylong12/real-lives-2007-python/issues/58)).
- **Ask for raise / promotion** — split into two separate actions
  on the career card. Raise = salary bump in same role. Promotion =
  ladder hop. At top of ladder, only raise is offered. Either can
  result in being fired if you push too aggressively with low
  performance
  ([#55](https://github.com/jippylong12/real-lives-2007-python/issues/55),
   [#63](https://github.com/jippylong12/real-lives-2007-python/issues/63)).
- **Synthetic ladder rungs** — extra entries the binary doesn't ship:
  athletics gets a 5-rung ladder (youth → amateur → semi-pro → pro →
  elite), military gets officer → commander, religious gets a 4-rung
  path, and arts gets per-discipline 3-rung ladders
  ([#59](https://github.com/jippylong12/real-lives-2007-python/issues/59)).
- **Freelance career mode** — 20+ jobs (writers, artists, musicians,
  street vendors, traditional medicine practitioners, the early
  athletics rungs) are now flagged freelance. Their earnings scale
  heavily with the relevant attribute and have a wide luck range each
  year. A freelance writer with artistic 95 takes home ~$2.5M over
  40 years; one with artistic 25 takes home ~$381k. The "starving
  artist" gap is real
  ([#61](https://github.com/jippylong12/real-lives-2007-python/issues/61)).
- **Talents and weaknesses** — every newborn now has 1-2 random
  talent attributes (+15-25 boost) and 1-2 weakness attributes
  (-10-18 penalty). Most characters are average overall with clear
  strong and weak suits
  ([#65](https://github.com/jippylong12/real-lives-2007-python/issues/65)).
- **Console logging** — all frontend actions log to DevTools through
  a `[RL]` tagged helper plus a global handler for unhandled promise
  rejections, surfaced after the silent button bug.

### Changed

- **Character attribute distribution** — Gaussian rolls instead of
  uniform, lower base means (intelligence 50→42, etc.). Across 200
  newborns only 4-8% have any single attribute >= 70. High-IQ-floor
  jobs are now genuinely competitive
  ([#65](https://github.com/jippylong12/real-lives-2007-python/issues/65)).
- **Working age gates** — the job board now enforces realistic
  minimum working ages by HDI (14 / 12 / 8). Babies, toddlers, and
  school-age kids in high-HDI countries can no longer apply for jobs
  ([#57](https://github.com/jippylong12/real-lives-2007-python/issues/57)).
- **Job board filters out far-too-young listings** so a 14-year-old
  doesn't see "doctor" in the long-shot view — only jobs they're
  close to age-eligible for
  ([#57](https://github.com/jippylong12/real-lives-2007-python/issues/57)).
- **Sidebar Job row layout** — action buttons moved into their own
  row below the Job stat. No more layout breakage when the job
  name is long ("company president")
  ([#62](https://github.com/jippylong12/real-lives-2007-python/issues/62)).
- **Salary scaling** — base salaries now multiply by `0.5 + skill/2`
  where skill is the character's relevant attribute / 60. Same job,
  different talent, different paycheck
  ([#60](https://github.com/jippylong12/real-lives-2007-python/issues/60)).

### Fixed

- **Finances panel was unreachable** after v1.1.0's collapsible
  refactor — the `<details>` panel started collapsed and the tab
  buttons inside the `<summary>` swallowed clicks via
  `stopPropagation`, so nothing could open it. Open by default + tabs
  moved out of summary
  ([#56](https://github.com/jippylong12/real-lives-2007-python/issues/56)).
- The "Start a new life" button used to silently fail when the
  cleanup code referenced a deleted DOM id. Wrapped in try/catch
  with surfaced errors.

## [1.1.0] — 2026-04-09

First feedback-driven update. Fixes 18 issues found during the v1.0.0
playthrough — gameplay bugs, calibration gaps, missing player agency, and
the layout/UX rough edges that made the game feel unfinished.

### Added

- **Player agency.** New choice events and actions where the original v1.0.0
  forced auto-decisions:
  - **Education path** at age 17 — university / vocational / drop out
    ([#42](https://github.com/jippylong12/real-lives-2007-python/issues/42)).
  - **Love marriage proposal** at 24-38 in countries where the existing
    arranged-marriage choice doesn't apply
    ([#43](https://github.com/jippylong12/real-lives-2007-python/issues/43)).
  - **Quit your job** action — career drift via a new
    `POST /api/game/{id}/quit_job` endpoint and a Quit button next to the
    job stat ([#38](https://github.com/jippylong12/real-lives-2007-python/issues/38)).
  - **Pay extra on a loan** action — `POST /api/game/{id}/pay_loan` plus a
    per-loan input in the loans tab. Loans no longer feel inescapable
    ([#40](https://github.com/jippylong12/real-lives-2007-python/issues/40)).
- **Country picker filtering** — search input + region tabs (All / Africa /
  Americas / Asia / Europe / Oceania), all client-side. Finding a specific
  country in 199 entries no longer means scrolling
  ([#33](https://github.com/jippylong12/real-lives-2007-python/issues/33)).
- **Death screen retrospective** — a stats grid (years lived, education,
  final job, net worth, marriage, children, diseases endured) and a
  full diseases list with chronic/active/resolved tags + acquisition age,
  on top of the existing timeline
  ([#35](https://github.com/jippylong12/real-lives-2007-python/issues/35)).
- **Console logging** — every action through `log()` / `logErr()` with
  `[RL]` tag and global handlers for unhandled promise rejections.
  Previously a thrown error in a click handler silently killed the UI;
  now you see exactly what failed in DevTools.
- `EventChoice.side_effect` callback hook — lets choice events mutate
  character state directly (used by the new education + marriage events).
- 7 new regression tests covering pregnancy, small business, loan
  repayment, quit job, lifespan, multi-disease behavior, and the loan
  age gate. **72 tests passing** (was 67).

### Changed

- **Lifespan calibration** — average simulated life expectancy is now in
  the real-world ballpark for healthy countries (US 78, Sweden 81, Norway
  83). HDI-scaled background mortality, regen drift extends past age 70,
  cause-of-death labels distinguish "old age" from "natural causes" by
  age + health rather than the old binary cliff
  ([#31](https://github.com/jippylong12/real-lives-2007-python/issues/31),
  [#32](https://github.com/jippylong12/real-lives-2007-python/issues/32)).
- **Choice events render in a modal** — backdrop, animated pop-in,
  blocks page interaction so the player can't miss them
  ([#46](https://github.com/jippylong12/real-lives-2007-python/issues/46)).
- **Event log: card grid + polarity coloring** — responsive grid
  (`auto-fill, minmax(220px)`), each card tints green / red / category-
  color based on its net delta. Compact layout fits multi-disease years
  without scrolling ([#45](https://github.com/jippylong12/real-lives-2007-python/issues/45)).
- **One-screen layout** — sidebar essentials (age, year, money, job,
  headline health bar) always visible; detailed sections (More stats,
  Attributes, Health & diseases, Country) collapse into native
  `<details>` elements. Finances and timeline panels in the main column
  collapse the same way. Aim is to fit a session on a 1440×900 viewport
  without scrolling ([#47](https://github.com/jippylong12/real-lives-2007-python/issues/47)).
- **Multi-disease years split into separate event log entries** instead
  of one wall-of-text card
  ([#36](https://github.com/jippylong12/real-lives-2007-python/issues/36)).
- **Disaster history reshaped** — `country.binary_facts.disaster_history`
  is now a list of `{kind, events, killed_per_event, affected_per_event}`
  records. The values are *per typical recorded event*, not cumulative
  totals (verified by cross-checking China earthquakes and Bangladesh
  floods). UI labels them as such
  ([#34](https://github.com/jippylong12/real-lives-2007-python/issues/34)).
- Small business and other risky investments now use the `risk` field
  for catastrophic-loss rolls — small business has ~6%/year failure
  chance, so the median 20-year hold is at or below the starting
  investment instead of compounding to millions
  ([#41](https://github.com/jippylong12/real-lives-2007-python/issues/41)).
- Disease wear from chronic conditions reduced (severity//6 for non-
  cancer permanents, severity//4 for cancers); convalescent regen
  boost when health drops below 25 so impaired characters can recover.

### Fixed

- **Pregnancy event actually adds a child** to `character.children`. The
  kids stat in the sidebar finally updates after a `had_child` event
  fires ([#39](https://github.com/jippylong12/real-lives-2007-python/issues/39)).
- **Loans are age-gated** — kids can no longer take out a mortgage.
  Standard loans require age 18, family loans 14
  ([#37](https://github.com/jippylong12/real-lives-2007-python/issues/37)).
- **"Start a new life" button silently failed** because the cleanup code
  in `newGame()` referenced `#decision-area` after issue #46 had renamed
  it to `#decision-modal`. Throwing on null + click-handler swallowed the
  error → dead button. Fixed and wrapped in try/catch.
- **Stale events from the previous life** no longer linger when starting
  a new game. `newGame()` now resets all the visible panels
  ([#44](https://github.com/jippylong12/real-lives-2007-python/issues/44)).

## [1.0.0] — 2026-04-09

First public release. A clean-room rebuild of *Real Lives 2007* as a
modern web app — runnable from source or as a downloadable desktop
binary on macOS Apple Silicon, Windows, or Linux.

### Highlights

- **199 countries** seeded from the original game's `world.dat` plus
  hand-curated additions for territories not in the binary
- **131 jobs** decoded directly from `jobs.dat`
- **60+ named diseases** with country-modulated incidence
- **Religion / culture / language-gated events** for ~30 countries
- **Investment + loan UI** with auto yearly tick
- **City-level birth granularity** (rural vs urban differentiation)
- **Country encyclopedia text** recovered from the binary's long-string pool
- **Cross-platform desktop bundle** via PyInstaller + GitHub Actions CI

### Closed issues

#1 disease model · #2 investments + loans · #3 city granularity ·
#4 country encyclopedia · #5 religion events · #6 binary decoder ·
#7 country expansion · #8 LICENSE · #9 city coverage ·
#10 urban/rural disease modulation · #11 description coverage ·
#12 boundary stitching · #13 encyclopedia keys · #14 disease calibration ·
#15 family_wealth fallback · #16 language/region events ·
#17 binary field catch-all · #18 binary value overlay ·
#19 generic .dat decoder · #20 type 4/5 distinction ·
#22 #23 #24 (multi-disease + tropical gating + cancer calibration) ·
#25 save-state docs · #26 IndexField · #27 CP437 encoding ·
#28 SanitationUrban clamp · #29 'No' sentinel · #30 frontend binary panel
