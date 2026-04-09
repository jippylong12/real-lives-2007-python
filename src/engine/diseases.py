"""
Disease registry: 50+ named conditions with realistic country/age modulation.

The original Real Lives 2007 binary tracks individual diseases as boolean flags
on the character (HasMalaria, HadStunting, HasTertiaryNeurologicalSyphilis, ...).
This module mirrors that resolution: instead of a single generic ``serious_illness``
event, the engine rolls a specific named condition each year, weighted by the
country's prevalence profile and the character's age band, and applies it to
``character.diseases`` so it can be displayed and inherited across years.

Treatment availability follows the country's health services and the player's
ability to pay; untreated severe cases run a per-year mortality lottery.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .character import Character
    from .world import Country


# Country region buckets for tropical-disease modulation. The 2007 Factbook
# treats tropical diseases as concentrated in Sub-Saharan Africa, tropical
# Latin America, Oceania, and the tropical Asia belt (Indian subcontinent +
# Southeast Asia). The "Asia" region bucket in seed.py includes both
# tropical and temperate countries (China, Japan, Korea, Mongolia, the
# 'stans), so we enumerate the tropical Asian country codes explicitly
# rather than including the whole region.
TROPICAL_REGIONS = {"Africa", "Central America", "Caribbean", "South America", "Oceania"}
TROPICAL_ASIA_CODES = frozenset({
    # Indian subcontinent
    "in", "bd", "lk", "np", "bt", "mv", "pk",
    # Southeast Asia
    "id", "my", "th", "vn", "kh", "la", "mm", "ph", "sg", "tl", "bn",
    # Middle East tropical pockets
    "ye", "om",
})


def is_tropical(country: "Country") -> bool:
    """Whether a country lies in the tropical-disease belt — used by
    ``tropical_only`` and the ``tropical_mult`` modifier."""
    return country.region in TROPICAL_REGIONS or country.code in TROPICAL_ASIA_CODES


@dataclass(frozen=True)
class Disease:
    key: str                    # unique snake_case id
    name: str                   # display name
    category: str               # cancer | sti | tropical | childhood | chronic | infectious | respiratory | mental
    base_chance: float          # annual base probability before modulation
    age_min: int                # earliest age the disease typically appears
    age_max: int                # latest typical onset age
    severity: int               # health points lost per year while active
    lethality: float            # extra death roll per year while active & untreated
    treatable: bool             # if True, good health services + money can cure
    treatment_cost: int         # USD-equivalent treatment cost
    permanent: bool = False     # condition leaves a lifelong mark even after "cure"
    gender_only: int | None = None  # 0 female, 1 male, None both
    tropical_only: bool = False # hard-zero outside TROPICAL_REGIONS (#23)
    tropical_mult: float = 1.0  # multiplier for TROPICAL_REGIONS
    poor_mult: float = 1.0      # multiplier when gdp_pc < 5000
    rich_mult: float = 1.0      # multiplier when gdp_pc > 30000
    sanitation_dependent: bool = False  # bigger penalty in countries with bad water
    # Urbanization skew (#10): >1.0 means urban-skewed (TB, depression, COPD,
    # asthma, lung cancer — anything driven by density, pollution, sedentary
    # lifestyle), <1.0 means rural-skewed (malaria, cholera, schistosomiasis,
    # hookworm — anything driven by poor sanitation or rural exposure).
    # Applied to is_urban characters as urban_skew, to !is_urban characters
    # as 1/urban_skew.
    urban_skew: float = 1.0
    description: str = ""


# 50+ diseases. Probabilities are intentionally low — diseases roll alongside
# every other yearly event, and the CDF over a full lifetime should produce
# realistic prevalence (e.g., ~13% lifetime risk of breast cancer in women).
DISEASES: list[Disease] = [
    # ===== Cancers (16) =====
    Disease("cancer_bladder",   "Bladder cancer",   "cancer", 0.0006, 50, 90, 8,  0.25, True, 30000, description="Tumor in the bladder lining."),
    Disease("cancer_breast",    "Breast cancer",    "cancer", 0.0020, 35, 90, 9,  0.20, True, 35000, gender_only=0, description="Tumor in breast tissue."),
    Disease("cancer_cervix",    "Cervical cancer",  "cancer", 0.0010, 25, 80, 9,  0.25, True, 25000, gender_only=0, poor_mult=2.5, rich_mult=0.5, description="Tumor of the cervix; preventable with screening."),
    Disease("cancer_colon",     "Colon cancer",     "cancer", 0.0014, 45, 90, 9,  0.25, True, 32000, description="Tumor of the colon."),
    Disease("cancer_esophagus", "Esophageal cancer","cancer", 0.0005, 50, 85, 10, 0.45, True, 40000, description="Tumor of the esophagus."),
    Disease("cancer_leukemia",  "Leukemia",         "cancer", 0.0006,  3, 85, 10, 0.30, True, 50000, description="Cancer of blood-forming tissue."),
    Disease("cancer_liver",     "Liver cancer",     "cancer", 0.0008, 45, 85, 11, 0.50, True, 38000, description="Hepatocellular carcinoma."),
    Disease("cancer_lung",      "Lung cancer",      "cancer", 0.0015, 45, 90, 11, 0.45, True, 42000, urban_skew=1.6, description="Most cases linked to tobacco use and urban air pollution."),
    Disease("cancer_lymphoma",  "Lymphoma",         "cancer", 0.0007, 25, 85, 9,  0.25, True, 38000, description="Cancer of the lymphatic system."),
    Disease("cancer_melanoma",  "Melanoma",         "cancer", 0.0006, 30, 85, 8,  0.20, True, 28000, description="Skin cancer."),
    Disease("cancer_mouth",     "Mouth cancer",     "cancer", 0.0005, 40, 85, 8,  0.30, True, 26000, description="Oral cavity tumor."),
    Disease("cancer_ovary",     "Ovarian cancer",   "cancer", 0.0008, 40, 80, 10, 0.35, True, 35000, gender_only=0, description="Tumor of the ovary."),
    Disease("cancer_pancreas",  "Pancreatic cancer","cancer", 0.0006, 50, 85, 12, 0.65, True, 45000, description="Highly lethal abdominal cancer."),
    Disease("cancer_prostate",  "Prostate cancer",  "cancer", 0.0018, 50, 90, 8,  0.18, True, 30000, gender_only=1, description="Most common cancer in older men."),
    Disease("cancer_stomach",   "Stomach cancer",   "cancer", 0.0006, 45, 85, 10, 0.40, True, 32000, description="Gastric carcinoma."),
    Disease("cancer_uterus",    "Uterine cancer",   "cancer", 0.0007, 45, 80, 8,  0.25, True, 28000, gender_only=0, description="Endometrial tumor."),

    # ===== Sexually transmitted (with staged syphilis) =====
    Disease("syphilis_primary",       "Primary syphilis",        "sti", 0.0015, 16, 60, 5, 0.02, True,  500, poor_mult=3.0, rich_mult=0.3, description="Painless chancre at the infection site."),
    Disease("syphilis_secondary",     "Secondary syphilis",      "sti", 0.0008, 16, 60, 7, 0.05, True, 1000, poor_mult=3.0, description="Rash and systemic symptoms; weeks after primary."),
    Disease("syphilis_tertiary_cv",   "Cardiovascular syphilis", "sti", 0.0002, 30, 80, 12, 0.30, True, 5000, permanent=True, description="Aortic damage from late syphilis."),
    Disease("syphilis_tertiary_neuro","Neurological syphilis",   "sti", 0.0002, 30, 80, 12, 0.30, True, 5000, permanent=True, description="Tabes dorsalis or general paresis from late syphilis."),
    Disease("syphilis_congenital",    "Congenital syphilis",     "sti", 0.0005,  0,  2, 10, 0.40, True,  800, poor_mult=4.0, description="Inherited from mother during pregnancy."),
    Disease("chlamydia",              "Chlamydia",               "sti", 0.0030, 16, 50, 3, 0.005, True, 200, description="Often asymptomatic; common bacterial STI."),
    Disease("chlamydia_pid",          "Pelvic inflammatory disease", "sti", 0.0008, 18, 50, 7, 0.03, True, 1500, gender_only=0, permanent=True, description="Untreated chlamydia or gonorrhea complication."),
    Disease("chlamydia_infertility",  "STI-related infertility", "sti", 0.0004, 20, 45, 0, 0.0, False, 0, permanent=True, description="Tubal damage from prior pelvic infection."),
    Disease("gonorrhea",              "Gonorrhea",               "sti", 0.0020, 16, 50, 4, 0.01, True, 250, description="Bacterial STI; treatable with antibiotics."),
    Disease("hiv",                    "HIV/AIDS",                "sti", 0.0010, 16, 60, 7, 0.10, True, 8000, permanent=True, poor_mult=4.0, rich_mult=0.4, urban_skew=1.5, description="Lifelong infection; manageable with antiretroviral therapy."),
    Disease("hpv",                    "HPV infection",           "sti", 0.0040, 16, 45, 1, 0.0, True, 0, description="Most clear naturally; some strains cause cancer."),

    # ===== Tropical / parasitic =====
    # tropical_only=True: hard-zeros incidence outside TROPICAL_REGIONS so we
    # don't need to balance fragile rich_mult/tropical_mult products to
    # almost-zero out malaria-in-Stockholm cases. rich_mult restored to
    # believable values (#23).
    Disease("malaria",          "Malaria",          "tropical", 0.0150,  0, 90, 10, 0.06, True, 100, sanitation_dependent=True, tropical_only=True, tropical_mult=8.0, rich_mult=0.3, urban_skew=0.4, description="Mosquito-borne parasitic infection; rural exposure dominates."),
    Disease("dengue",           "Dengue fever",     "tropical", 0.0080,  3, 80, 8,  0.02, True, 300, tropical_only=True, tropical_mult=5.0, rich_mult=0.3, description="Viral fever transmitted by Aedes mosquitoes."),
    Disease("yellow_fever",     "Yellow fever",     "tropical", 0.0010,  5, 70, 12, 0.20, True, 800, tropical_only=True, tropical_mult=6.0, rich_mult=0.2, description="Viral hemorrhagic fever; vaccine-preventable."),
    Disease("chagas",           "Chagas disease",   "tropical", 0.0008,  5, 80, 5, 0.04, True, 1500, permanent=True, tropical_only=True, tropical_mult=4.0, rich_mult=0.1, description="Trypanosoma cruzi; chronic cardiac damage."),
    Disease("leishmaniasis",    "Leishmaniasis",    "tropical", 0.0009,  5, 70, 8, 0.10, True, 1200, tropical_only=True, tropical_mult=5.0, rich_mult=0.1, description="Sandfly-transmitted protozoan disease."),
    Disease("sleeping_sickness","Sleeping sickness","tropical", 0.0004, 10, 70, 12, 0.40, True, 2000, tropical_only=True, tropical_mult=10.0, rich_mult=0.05, description="African trypanosomiasis."),
    Disease("schistosomiasis",  "Schistosomiasis",  "tropical", 0.0050,  5, 70, 4, 0.005, True, 200, sanitation_dependent=True, tropical_only=True, tropical_mult=6.0, rich_mult=0.1, urban_skew=0.3, description="Snail-borne parasitic worm; rural water exposure."),
    Disease("onchocerciasis",   "River blindness",  "tropical", 0.0006,  8, 70, 4, 0.005, True, 400, permanent=True, tropical_only=True, tropical_mult=8.0, rich_mult=0.05, description="Onchocerca volvulus; can cause blindness."),
    Disease("trichuriasis",     "Whipworm",         "tropical", 0.0090,  3, 60, 2, 0.0, True, 50, sanitation_dependent=True, tropical_only=True, tropical_mult=4.0, rich_mult=0.2, description="Soil-transmitted intestinal worm."),
    Disease("ascariasis",       "Roundworm",        "tropical", 0.0090,  3, 60, 2, 0.0, True, 50, sanitation_dependent=True, tropical_only=True, tropical_mult=4.0, rich_mult=0.2, description="Soil-transmitted intestinal worm."),
    Disease("hookworm",         "Hookworm",         "tropical", 0.0060,  5, 60, 3, 0.005, True, 80, sanitation_dependent=True, tropical_only=True, tropical_mult=4.0, rich_mult=0.2, urban_skew=0.3, description="Iron-deficiency anemia from blood-feeding worms; rural soil exposure."),

    # ===== Childhood =====
    Disease("measles",          "Measles",          "childhood", 0.0080,  0, 12, 6, 0.04, True, 50, poor_mult=3.0, rich_mult=0.1, description="Highly contagious viral rash."),
    Disease("mumps",            "Mumps",            "childhood", 0.0040,  3, 15, 4, 0.005, True, 30, rich_mult=0.2, description="Salivary gland infection."),
    Disease("rubella",          "Rubella",          "childhood", 0.0030,  3, 15, 3, 0.005, True, 30, rich_mult=0.2, description="German measles; teratogenic in pregnancy."),
    Disease("polio",            "Polio",            "childhood", 0.0008,  0, 10, 10, 0.10, True, 200, permanent=True, poor_mult=5.0, rich_mult=0.0, description="Viral paralysis; rare since widespread vaccination."),
    Disease("pertussis",        "Whooping cough",   "childhood", 0.0050,  0,  8, 5, 0.04, True, 80, poor_mult=2.0, rich_mult=0.3, description="Bordetella pertussis; severe in infants."),
    Disease("diphtheria",       "Diphtheria",       "childhood", 0.0008,  0, 12, 8, 0.15, True, 100, poor_mult=4.0, rich_mult=0.05, description="Throat membrane infection; vaccine-preventable."),
    Disease("chickenpox",       "Chickenpox",       "childhood", 0.0150,  2, 14, 3, 0.002, True, 30, description="Varicella; usually mild."),
    Disease("stunting",         "Childhood stunting","childhood", 0.0200, 0,  5, 4, 0.005, False, 0, permanent=True, poor_mult=4.0, rich_mult=0.05, description="Chronic malnutrition impairs growth and cognition."),
    Disease("wasting",          "Childhood wasting","childhood", 0.0100,  0,  5, 6, 0.02, True, 200, permanent=True, poor_mult=4.0, rich_mult=0.05, description="Acute severe undernutrition."),

    # ===== Chronic =====
    Disease("diabetes_t2",      "Type 2 diabetes",  "chronic", 0.0180, 35, 85, 4, 0.01, True, 1500, permanent=True, rich_mult=1.5, description="Insulin resistance; managed with diet and medication."),
    Disease("diabetes_t1",      "Type 1 diabetes",  "chronic", 0.0010,  3, 30, 5, 0.02, True, 2000, permanent=True, description="Autoimmune destruction of insulin-producing cells."),
    Disease("hypertension",     "Hypertension",     "chronic", 0.0350, 30, 85, 3, 0.02, True, 800, permanent=True, description="Chronic high blood pressure."),
    Disease("heart_disease",    "Coronary heart disease", "chronic", 0.0160, 40, 90, 9, 0.10, True, 12000, permanent=True, rich_mult=1.2, description="Atherosclerosis of the coronary arteries."),
    Disease("stroke",           "Stroke",           "chronic", 0.0015, 50, 90, 12, 0.20, True, 8000, permanent=True, description="Brain blood-supply interruption; cerebrovascular accident."),
    Disease("asthma",           "Asthma",           "chronic", 0.0040,  3, 80, 3, 0.005, True, 600, permanent=True, urban_skew=1.4, description="Chronic inflammatory airway disease; urban air pollution."),
    Disease("copd",             "COPD",             "chronic", 0.0020, 40, 85, 6, 0.05, True, 1500, permanent=True, urban_skew=1.5, description="Chronic obstructive pulmonary disease; pollution-driven."),
    Disease("arthritis",        "Arthritis",        "chronic", 0.0140, 40, 90, 3, 0.0, True, 800, permanent=True, description="Joint inflammation; rheumatoid or osteo."),
    Disease("kidney_disease",   "Chronic kidney disease", "chronic", 0.0015, 45, 85, 7, 0.08, True, 6000, permanent=True, description="Reduced kidney function."),

    # ===== Infectious =====
    Disease("tuberculosis",     "Tuberculosis",     "infectious", 0.0040, 5, 80, 8, 0.07, True, 600, sanitation_dependent=True, poor_mult=4.0, rich_mult=0.1, urban_skew=1.8, description="Mycobacterium tuberculosis; airborne, dense-urban skewed."),
    Disease("hepatitis_a",      "Hepatitis A",      "infectious", 0.0030, 3, 60, 5, 0.005, True, 200, sanitation_dependent=True, poor_mult=3.0, description="Fecal-oral viral hepatitis."),
    Disease("hepatitis_b",      "Hepatitis B",      "infectious", 0.0020, 5, 70, 6, 0.03, True, 800, permanent=True, poor_mult=2.5, rich_mult=0.4, description="Blood-borne viral hepatitis."),
    Disease("hepatitis_c",      "Hepatitis C",      "infectious", 0.0015, 18, 70, 7, 0.04, True, 1500, permanent=True, description="Blood-borne; can lead to cirrhosis."),
    Disease("cholera",          "Cholera",          "infectious", 0.0030, 3, 70, 9, 0.10, True, 100, sanitation_dependent=True, poor_mult=5.0, rich_mult=0.0, urban_skew=0.5, description="Severe watery diarrhea from contaminated water; rural sanitation."),
    Disease("typhoid",          "Typhoid fever",    "infectious", 0.0020, 5, 60, 7, 0.06, True, 200, sanitation_dependent=True, poor_mult=3.0, rich_mult=0.05, description="Salmonella Typhi infection."),
    Disease("meningitis",       "Meningitis",       "infectious", 0.0010, 0, 25, 12, 0.20, True, 1500, description="Inflammation of meninges; can be bacterial or viral."),
    Disease("pneumonia",        "Pneumonia",        "infectious", 0.0080, 0, 90, 7, 0.05, True, 600, description="Lung infection."),
    Disease("tetanus",          "Tetanus",          "infectious", 0.0006, 5, 70, 12, 0.25, True, 400, poor_mult=3.0, rich_mult=0.1, description="Clostridium tetani; lockjaw."),
    Disease("rabies",           "Rabies",           "infectious", 0.0002, 3, 70, 15, 0.95, True, 800, poor_mult=4.0, rich_mult=0.1, description="Almost always fatal once symptomatic."),

    # ===== Respiratory =====
    Disease("influenza",        "Severe influenza", "respiratory", 0.0150, 1, 90, 4, 0.005, True, 100, description="Seasonal flu, severe enough to need bed rest."),
    Disease("bronchitis",       "Bronchitis",       "respiratory", 0.0100, 2, 80, 3, 0.002, True, 80, description="Inflammation of bronchial tubes."),

    # ===== Mental health =====
    Disease("depression",       "Major depression", "mental", 0.0080, 14, 80, 5, 0.02, True, 1500, urban_skew=1.4, description="Persistent depressive episode; urban isolation correlates."),
    Disease("anxiety",          "Anxiety disorder", "mental", 0.0070, 14, 80, 3, 0.0, True, 1000, description="Generalized anxiety or panic disorder."),
]


# ---------------------------------------------------------------------------
# Roll & apply
# ---------------------------------------------------------------------------

def _country_modifier(disease: Disease, country: "Country") -> float:
    mult = 1.0
    if disease.tropical_mult != 1.0 and is_tropical(country):
        mult *= disease.tropical_mult
    if disease.poor_mult != 1.0 and country.gdp_pc < 5000:
        mult *= disease.poor_mult
    if disease.rich_mult != 1.0 and country.gdp_pc > 30000:
        mult *= disease.rich_mult
    if disease.sanitation_dependent and country.safe_water_pct < 80:
        mult *= 1.0 + (80 - country.safe_water_pct) * 0.04
    return mult


def _urbanization_modifier(disease: Disease, character: "Character") -> float:
    """Apply the disease's urban_skew to the character's residence (#10).

    urban_skew > 1.0 → urban-skewed disease (TB, COPD, depression). Urban
    characters get the multiplier; rural characters get its reciprocal.
    urban_skew < 1.0 → rural-skewed disease (malaria, cholera, hookworm).
    Same logic — urban characters get the (sub-1) multiplier, rural ones
    get the reciprocal (>1).
    """
    if disease.urban_skew == 1.0:
        return 1.0
    return disease.urban_skew if character.is_urban else 1.0 / disease.urban_skew


def eligible_diseases(character: "Character", country: "Country") -> list[tuple[Disease, float]]:
    """Return (disease, modulated annual chance) pairs the character can newly contract."""
    out: list[tuple[Disease, float]] = []
    active = set(character.diseases.keys())
    for d in DISEASES:
        if character.age < d.age_min or character.age > d.age_max:
            continue
        if d.gender_only is not None and int(character.gender) != d.gender_only:
            continue
        # Hard gate: tropical-only diseases (#23) don't appear at all
        # outside the tropical belt. Avoids fragile rich_mult juggling for
        # malaria-in-Stockholm.
        if d.tropical_only and not is_tropical(country):
            continue
        if d.key in active:
            continue
        chance = d.base_chance * _country_modifier(d, country) * _urbanization_modifier(d, character)
        # Resistance and health services dampen incidence — but only for
        # categories where the immune system / preventive care can plausibly
        # block onset. Chronic conditions and cancers are driven by genetics,
        # diet, age, and pollution, not infection resistance, so they bypass
        # these modifiers (#22).
        if d.category not in {"chronic", "cancer", "mental"}:
            chance *= max(0.2, 2.0 - character.attributes.resistance / 50)
            if not d.sanitation_dependent:
                chance *= max(0.5, 1.5 - country.health_services_pct / 100)
        out.append((d, chance))
    return out


# Categories that are *acute* — capped at one per year so a character
# doesn't get five different respiratory infections in the same calendar
# year. Chronic / cancer / mental categories are silent and can accumulate
# freely, which is what makes lifetime prevalence land in the right
# ballpark for hypertension, diabetes, heart disease, etc.
_ACUTE_CATEGORIES = {"infectious", "respiratory", "childhood", "sti", "tropical"}


def roll_diseases(character: "Character", country: "Country", rng: random.Random) -> list[Disease]:
    """Roll independently for each eligible disease per year (#22).

    Each disease gets its own Bernoulli trial against its modulated annual
    chance. Acute categories (infectious, respiratory, childhood, STI,
    tropical) are capped at one disease per year so a character doesn't
    contract flu + bronchitis + pneumonia + TB in the same calendar year.
    Silent categories (chronic, cancer, mental) accumulate freely — that's
    what allows lifetime hypertension/diabetes/cancer prevalence to reach
    realistic levels.
    """
    candidates = eligible_diseases(character, country)
    if not candidates:
        return []
    fired: list[Disease] = []
    capped_categories: set[str] = set()
    for d, chance in candidates:
        if d.category in _ACUTE_CATEGORIES and d.category in capped_categories:
            continue
        if rng.random() < chance:
            fired.append(d)
            if d.category in _ACUTE_CATEGORIES:
                capped_categories.add(d.category)
    return fired


def roll_disease(character: "Character", country: "Country", rng: random.Random) -> Disease | None:
    """Backwards-compat: return the first disease that fires this year, or
    None. Prefer :func:`roll_diseases` for full multi-disease behavior."""
    fired = roll_diseases(character, country, rng)
    return fired[0] if fired else None


def contract_disease(
    character: "Character", country: "Country", disease: Disease, rng: random.Random
) -> dict:
    """Add a disease to the character's record. Returns a serialized event
    payload (summary, deltas, money_delta) for the engine's turn log."""
    # Mark active.
    character.diseases[disease.key] = {
        "name": disease.name,
        "category": disease.category,
        "active": True,
        "age_acquired": character.age,
        "permanent": disease.permanent,
    }

    # Treatment availability: requires good local health services AND the
    # player can afford the treatment from cash + family wealth.
    can_pay = character.money + character.family_wealth >= disease.treatment_cost
    has_services = country.health_services_pct >= 60
    treatable = disease.treatable and has_services and can_pay
    cost = 0
    if treatable and disease.treatment_cost > 0:
        cost = disease.treatment_cost
        # Drain personal money first, then dip into family_wealth for the rest.
        # (Affordability already required money + family_wealth >= cost.)
        from_money = min(character.money, cost)
        character.money -= from_money
        remaining = cost - from_money
        if remaining > 0:
            character.family_wealth -= remaining

    severity = disease.severity
    if treatable:
        severity = max(1, severity // 2)
        if not disease.permanent:
            character.diseases[disease.key]["active"] = False
            character.diseases[disease.key]["age_resolved"] = character.age

    deltas = {"health": -severity, "happiness": -3}
    if disease.category == "mental":
        deltas["happiness"] = -8
        deltas["health"] = -severity // 2

    if treatable:
        if disease.permanent:
            summary = (
                f"You were diagnosed with {disease.name}. "
                f"Treatment cost ${cost:,} but the condition will require ongoing care."
            )
        else:
            summary = (
                f"You contracted {disease.name}. Treatment (${cost:,}) cleared the infection."
            )
    else:
        if disease.treatable and not has_services:
            summary = (
                f"You contracted {disease.name}, but local health services were too "
                f"limited to treat it properly."
            )
        elif disease.treatable and not can_pay:
            summary = (
                f"You contracted {disease.name}, but couldn't afford the ${disease.treatment_cost:,} treatment."
            )
        else:
            summary = f"You developed {disease.name}. There is no straightforward cure."

    return {
        "summary": summary,
        "deltas": deltas,
        "money_delta": -cost,
        "treatable": treatable,
    }


def chronic_progression(character: "Character", country: "Country", rng: random.Random) -> tuple[int, list[str]]:
    """Apply per-year wear from any active chronic / permanent conditions and
    perform a death lottery for severe untreated diseases. Returns (health_loss,
    notable_summary_lines).
    """
    total_loss = 0
    lines: list[str] = []
    deaths_pending: list[str] = []
    for key, state in list(character.diseases.items()):
        if not state.get("active"):
            continue
        d = next((dd for dd in DISEASES if dd.key == key), None)
        if d is None:
            continue
        # Permanent / chronic conditions degrade health each year.
        wear = max(1, d.severity // 3) if d.permanent else 0
        total_loss += wear
        # Death lottery for severe conditions.
        if d.lethality > 0:
            if rng.random() < d.lethality * 0.5:  # half rate after acquisition year
                deaths_pending.append(d.name)
    if deaths_pending:
        lines.append(f"Your {deaths_pending[0]} took a turn for the worse this year.")
    return total_loss, lines


def disease_kill_check(character: "Character", country: "Country", rng: random.Random) -> str | None:
    """Per-year roll: if the character has a high-lethality active disease,
    they may die from it. Returns the cause-of-death string or None."""
    for key, state in list(character.diseases.items()):
        if not state.get("active"):
            continue
        d = next((dd for dd in DISEASES if dd.key == key), None)
        if d is None:
            continue
        if d.lethality <= 0:
            continue
        if rng.random() < d.lethality * 0.4:
            return d.name
    return None
