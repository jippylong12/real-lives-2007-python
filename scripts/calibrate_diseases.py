"""
Disease incidence calibration tool (#14).

Simulates many lives in a set of anchor countries and reports lifetime
incidence per disease, so the curated values in src/engine/diseases.py
can be tuned against real-world prevalence data.

Usage:
    python -m scripts.calibrate_diseases               # all anchors
    python -m scripts.calibrate_diseases ng se in      # specific country codes

Real-world reference points (lifetime risk, approximate):
    malaria        Sweden  <0.1%   Nigeria ~95%   US <0.1%
    tuberculosis   Sweden  ~1%     Nigeria ~30%   US ~1%
    diabetes_t2    US      ~40%    Japan   ~10%   Sweden ~10%
    hypertension   US      ~80%    Sweden  ~30%   Japan ~30%
    cancer_lung    US      ~6%     Japan   ~4%
    cancer_breast  Women US ~13%   Sweden ~10%
    hiv            South Africa ~20%
    cholera        Bangladesh ~5%/year endemic regions

Discrepancies are expected — the disease roller fires at most one
disease per year, capping cumulative chronic incidence.
"""

from __future__ import annotations

import sys
from collections import defaultdict

from src.engine import Game


ANCHOR_COUNTRIES = ["se", "ng", "us", "jp", "in", "br", "za"]
ANCHOR_DISEASES = [
    "malaria",
    "tuberculosis",
    "hiv",
    "cholera",
    "diabetes_t2",
    "hypertension",
    "heart_disease",
    "cancer_breast",
    "cancer_lung",
    "cancer_prostate",
    "cancer_colon",
    "arthritis",
    "stroke",
    "depression",
]


def lifetime_incidence(country_code: str, n_lives: int = 200) -> dict[str, float]:
    """Simulate `n_lives` random lives in `country_code` and return per-disease
    lifetime incidence as a fraction of the cohort."""
    counts: dict[str, int] = defaultdict(int)
    for seed in range(n_lives):
        g = Game.new(country_code=country_code, seed=seed)
        while g.state.character.alive and g.state.character.age < 90:
            r = g.advance_year()
            if r.pending_decision:
                g.apply_decision(r.pending_decision["choices"][0]["key"])
        for k in g.state.character.diseases:
            counts[k] += 1
    return {k: v / n_lives for k, v in counts.items()}


def main(argv: list[str]) -> int:
    countries = argv[1:] if len(argv) > 1 else ANCHOR_COUNTRIES
    print(f"Simulating 200 lives per country for: {', '.join(countries)}")
    print()
    header = "disease".ljust(18) + " ".join(c.rjust(8) for c in countries)
    print(header)
    print("-" * len(header))
    rates = {c: lifetime_incidence(c) for c in countries}
    for d in ANCHOR_DISEASES:
        line = d.ljust(18)
        for c in countries:
            v = rates[c].get(d, 0.0) * 100
            line += f"{v:7.1f}% "
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
