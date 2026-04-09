# Changelog

All notable changes to Real Lives 2007 (Python rebuild).

The format is [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
