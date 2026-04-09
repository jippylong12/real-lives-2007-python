"""
Curated real-world statistics for the Real Lives 2007 Python rebuild.

The original game's .dat files store numeric country values inside Delphi
serialized records that this project's parser cannot fully decode (extended-
precision floats and dynamic arrays). Rather than ship a half-broken parser,
we ship a curated table of real-world country statistics here, sourced from
the same kinds of public datasets the original game pulled from in 2007:

  - Population:        UN World Population Prospects / World Bank
  - GDP per capita:    World Bank (PPP, USD)
  - Life expectancy:   World Bank
  - Infant mortality:  UNICEF State of the World's Children
  - Literacy:          UNESCO Institute for Statistics
  - GINI:              World Bank
  - HDI:               UNDP Human Development Report
  - Religion / langs:  CIA World Factbook
  - War/disaster freq: EM-DAT, Uppsala Conflict Data Program

The parser-recovered country name list (from data/world.dat) is the canonical
country set; this dict provides per-country numeric attributes.

Adding more countries: copy any entry as a template and fill in real values.
The game engine tolerates missing fields by falling back to continent medians.
"""

# Continent / region medians used as fallbacks for any country not listed below.
REGION_DEFAULTS: dict[str, dict] = {
    "Africa":           {"life_expectancy": 62, "infant_mortality": 48, "literacy": 65, "gdp_pc": 3500,  "gini": 43, "hdi": 0.55, "war_freq": 0.04, "disaster_freq": 0.05},
    "Asia":             {"life_expectancy": 73, "infant_mortality": 22, "literacy": 85, "gdp_pc": 12000, "gini": 36, "hdi": 0.72, "war_freq": 0.02, "disaster_freq": 0.07},
    "Europe":           {"life_expectancy": 80, "infant_mortality":  4, "literacy": 99, "gdp_pc": 38000, "gini": 31, "hdi": 0.88, "war_freq": 0.005, "disaster_freq": 0.02},
    "North America":    {"life_expectancy": 78, "infant_mortality":  6, "literacy": 99, "gdp_pc": 50000, "gini": 38, "hdi": 0.89, "war_freq": 0.005, "disaster_freq": 0.04},
    "South America":    {"life_expectancy": 75, "infant_mortality": 14, "literacy": 93, "gdp_pc": 14000, "gini": 47, "hdi": 0.76, "war_freq": 0.01, "disaster_freq": 0.05},
    "Oceania":          {"life_expectancy": 78, "infant_mortality": 16, "literacy": 90, "gdp_pc": 30000, "gini": 35, "hdi": 0.78, "war_freq": 0.005, "disaster_freq": 0.05},
    "Central America":  {"life_expectancy": 74, "infant_mortality": 16, "literacy": 90, "gdp_pc": 13000, "gini": 46, "hdi": 0.74, "war_freq": 0.01, "disaster_freq": 0.05},
    "Caribbean":        {"life_expectancy": 73, "infant_mortality": 22, "literacy": 86, "gdp_pc": 11000, "gini": 44, "hdi": 0.72, "war_freq": 0.01, "disaster_freq": 0.07},
}


# Hand-curated country statistics. ~60 countries spanning every region — enough
# variety that random birth produces meaningfully different lives. Numbers are
# approximate real-world values (rounded; not warrantied as up-to-the-minute).
#
# Schema:
#   code:               ISO 3166-1 alpha-2 lowercase (matches data/flags/<code>.bmp)
#   region:             coarse continent bucket used for defaults
#   population:         total inhabitants
#   gdp_pc:             GDP per capita PPP (USD)
#   life_expectancy:    average years at birth (both sexes)
#   infant_mortality:   per 1000 live births
#   literacy:           % adult literacy rate
#   gini:               Gini coefficient * 100 (higher = more unequal)
#   hdi:                Human Development Index (0..1)
#   urban_pct:          % living in urban areas
#   primary_religion:   most-followed faith
#   primary_language:   most-spoken language
#   capital:            capital city name
#   currency:           local currency name
#   war_freq:           probability/year of a war event impacting the player
#   disaster_freq:      probability/year of a natural disaster event
#   crime_rate:         relative property crime risk (0..1)
#   corruption:         0..100, higher = more corrupt government
#   safe_water_pct:     % of population with safe drinking water
#   health_services_pct:% with access to health services
#
COUNTRIES: list[dict] = [
    # ===== Africa =====
    {"code": "ng", "name": "Nigeria",        "region": "Africa",        "population": 218000000, "gdp_pc":  5200, "life_expectancy": 55, "infant_mortality": 72, "literacy": 62, "gini": 35, "hdi": 0.54, "urban_pct": 53, "primary_religion": "Islam",          "primary_language": "English",    "capital": "Abuja",        "currency": "Naira",         "war_freq": 0.05, "disaster_freq": 0.04, "crime_rate": 0.55, "corruption": 75, "safe_water_pct": 78, "health_services_pct": 60},
    {"code": "et", "name": "Ethiopia",       "region": "Africa",        "population": 120000000, "gdp_pc":  2800, "life_expectancy": 67, "infant_mortality": 36, "literacy": 52, "gini": 35, "hdi": 0.50, "urban_pct": 22, "primary_religion": "Christianity",   "primary_language": "Amharic",    "capital": "Addis Ababa",  "currency": "Birr",          "war_freq": 0.06, "disaster_freq": 0.05, "crime_rate": 0.30, "corruption": 65, "safe_water_pct": 69, "health_services_pct": 55},
    {"code": "za", "name": "South Africa",   "region": "Africa",        "population":  60000000, "gdp_pc": 14000, "life_expectancy": 64, "infant_mortality": 27, "literacy": 87, "gini": 63, "hdi": 0.71, "urban_pct": 67, "primary_religion": "Christianity",   "primary_language": "Zulu",       "capital": "Pretoria",     "currency": "Rand",          "war_freq": 0.005,"disaster_freq": 0.03, "crime_rate": 0.78, "corruption": 56, "safe_water_pct": 93, "health_services_pct": 80},
    {"code": "eg", "name": "Egypt",          "region": "Africa",        "population": 110000000, "gdp_pc": 14000, "life_expectancy": 71, "infant_mortality": 17, "literacy": 73, "gini": 31, "hdi": 0.73, "urban_pct": 43, "primary_religion": "Islam",          "primary_language": "Arabic",     "capital": "Cairo",        "currency": "Egyptian pound","war_freq": 0.02, "disaster_freq": 0.02, "crime_rate": 0.30, "corruption": 67, "safe_water_pct": 99, "health_services_pct": 90},
    {"code": "ke", "name": "Kenya",          "region": "Africa",        "population":  55000000, "gdp_pc":  5800, "life_expectancy": 67, "infant_mortality": 29, "literacy": 82, "gini": 41, "hdi": 0.58, "urban_pct": 29, "primary_religion": "Christianity",   "primary_language": "Swahili",    "capital": "Nairobi",      "currency": "Shilling",      "war_freq": 0.02, "disaster_freq": 0.05, "crime_rate": 0.55, "corruption": 70, "safe_water_pct": 63, "health_services_pct": 60},
    {"code": "gh", "name": "Ghana",          "region": "Africa",        "population":  33000000, "gdp_pc":  6800, "life_expectancy": 64, "infant_mortality": 32, "literacy": 79, "gini": 43, "hdi": 0.63, "urban_pct": 58, "primary_religion": "Christianity",   "primary_language": "English",    "capital": "Accra",        "currency": "Cedi",          "war_freq": 0.005,"disaster_freq": 0.03, "crime_rate": 0.45, "corruption": 56, "safe_water_pct": 86, "health_services_pct": 70},
    {"code": "ma", "name": "Morocco",        "region": "Africa",        "population":  37000000, "gdp_pc":  9500, "life_expectancy": 77, "infant_mortality": 18, "literacy": 75, "gini": 40, "hdi": 0.69, "urban_pct": 64, "primary_religion": "Islam",          "primary_language": "Arabic",     "capital": "Rabat",        "currency": "Dirham",        "war_freq": 0.005,"disaster_freq": 0.03, "crime_rate": 0.35, "corruption": 60, "safe_water_pct": 87, "health_services_pct": 75},
    {"code": "cd", "name": "DR Congo",       "region": "Africa",        "population":  95000000, "gdp_pc":  1300, "life_expectancy": 60, "infant_mortality": 63, "literacy": 80, "gini": 42, "hdi": 0.48, "urban_pct": 46, "primary_religion": "Christianity",   "primary_language": "French",     "capital": "Kinshasa",     "currency": "Congolese franc","war_freq": 0.10,"disaster_freq": 0.04, "crime_rate": 0.60, "corruption": 80, "safe_water_pct": 46, "health_services_pct": 35},

    # ===== Middle East =====
    {"code": "sa", "name": "Saudi Arabia",   "region": "Asia",          "population":  36000000, "gdp_pc": 55000, "life_expectancy": 75, "infant_mortality":  6, "literacy": 96, "gini": 46, "hdi": 0.85, "urban_pct": 84, "primary_religion": "Islam",          "primary_language": "Arabic",     "capital": "Riyadh",       "currency": "Riyal",         "war_freq": 0.01, "disaster_freq": 0.01, "crime_rate": 0.10, "corruption": 47, "safe_water_pct": 99, "health_services_pct": 95},
    {"code": "ir", "name": "Iran",           "region": "Asia",          "population":  88000000, "gdp_pc": 18000, "life_expectancy": 77, "infant_mortality": 13, "literacy": 86, "gini": 41, "hdi": 0.78, "urban_pct": 76, "primary_religion": "Islam",          "primary_language": "Persian",    "capital": "Tehran",       "currency": "Rial",          "war_freq": 0.01, "disaster_freq": 0.05, "crime_rate": 0.25, "corruption": 72, "safe_water_pct": 96, "health_services_pct": 90},
    {"code": "iq", "name": "Iraq",           "region": "Asia",          "population":  43000000, "gdp_pc": 11000, "life_expectancy": 72, "infant_mortality": 22, "literacy": 86, "gini": 30, "hdi": 0.69, "urban_pct": 71, "primary_religion": "Islam",          "primary_language": "Arabic",     "capital": "Baghdad",      "currency": "Dinar",         "war_freq": 0.12, "disaster_freq": 0.02, "crime_rate": 0.55, "corruption": 80, "safe_water_pct": 96, "health_services_pct": 85},
    {"code": "il", "name": "Israel",         "region": "Asia",          "population":   9500000, "gdp_pc": 49000, "life_expectancy": 83, "infant_mortality":  3, "literacy": 98, "gini": 39, "hdi": 0.92, "urban_pct": 92, "primary_religion": "Judaism",        "primary_language": "Hebrew",     "capital": "Jerusalem",    "currency": "Shekel",        "war_freq": 0.04, "disaster_freq": 0.01, "crime_rate": 0.20, "corruption": 39, "safe_water_pct": 100,"health_services_pct": 98},
    {"code": "tr", "name": "Turkey",         "region": "Asia",          "population":  85000000, "gdp_pc": 31000, "life_expectancy": 77, "infant_mortality":  9, "literacy": 96, "gini": 42, "hdi": 0.84, "urban_pct": 76, "primary_religion": "Islam",          "primary_language": "Turkish",    "capital": "Ankara",       "currency": "Lira",          "war_freq": 0.01, "disaster_freq": 0.05, "crime_rate": 0.30, "corruption": 65, "safe_water_pct": 100,"health_services_pct": 92},
    {"code": "af", "name": "Afghanistan",    "region": "Asia",          "population":  40000000, "gdp_pc":  2000, "life_expectancy": 64, "infant_mortality": 53, "literacy": 38, "gini": 30, "hdi": 0.48, "urban_pct": 26, "primary_religion": "Islam",          "primary_language": "Pashto",     "capital": "Kabul",        "currency": "Afghani",       "war_freq": 0.18, "disaster_freq": 0.07, "crime_rate": 0.50, "corruption": 84, "safe_water_pct": 78, "health_services_pct": 50},

    # ===== South Asia =====
    {"code": "in", "name": "India",          "region": "Asia",          "population":1420000000, "gdp_pc":  8200, "life_expectancy": 70, "infant_mortality": 28, "literacy": 78, "gini": 35, "hdi": 0.63, "urban_pct": 35, "primary_religion": "Hinduism",       "primary_language": "Hindi",      "capital": "New Delhi",    "currency": "Rupee",         "war_freq": 0.01, "disaster_freq": 0.10, "crime_rate": 0.40, "corruption": 60, "safe_water_pct": 93, "health_services_pct": 65},
    {"code": "pk", "name": "Pakistan",       "region": "Asia",          "population": 240000000, "gdp_pc":  6300, "life_expectancy": 67, "infant_mortality": 55, "literacy": 58, "gini": 32, "hdi": 0.54, "urban_pct": 37, "primary_religion": "Islam",          "primary_language": "Urdu",       "capital": "Islamabad",    "currency": "Rupee",         "war_freq": 0.04, "disaster_freq": 0.08, "crime_rate": 0.50, "corruption": 73, "safe_water_pct": 91, "health_services_pct": 60},
    {"code": "bd", "name": "Bangladesh",     "region": "Asia",          "population": 170000000, "gdp_pc":  6300, "life_expectancy": 73, "infant_mortality": 24, "literacy": 75, "gini": 32, "hdi": 0.66, "urban_pct": 39, "primary_religion": "Islam",          "primary_language": "Bengali",    "capital": "Dhaka",        "currency": "Taka",          "war_freq": 0.005,"disaster_freq": 0.20, "crime_rate": 0.40, "corruption": 74, "safe_water_pct": 98, "health_services_pct": 60},
    {"code": "lk", "name": "Sri Lanka",      "region": "Asia",          "population":  22000000, "gdp_pc": 14000, "life_expectancy": 77, "infant_mortality":  6, "literacy": 92, "gini": 39, "hdi": 0.78, "urban_pct": 19, "primary_religion": "Buddhism",       "primary_language": "Sinhala",    "capital": "Colombo",      "currency": "Rupee",         "war_freq": 0.02, "disaster_freq": 0.05, "crime_rate": 0.30, "corruption": 63, "safe_water_pct": 92, "health_services_pct": 95},
    {"code": "np", "name": "Nepal",          "region": "Asia",          "population":  30000000, "gdp_pc":  4400, "life_expectancy": 71, "infant_mortality": 24, "literacy": 68, "gini": 33, "hdi": 0.60, "urban_pct": 21, "primary_religion": "Hinduism",       "primary_language": "Nepali",     "capital": "Kathmandu",    "currency": "Rupee",         "war_freq": 0.02, "disaster_freq": 0.10, "crime_rate": 0.30, "corruption": 67, "safe_water_pct": 95, "health_services_pct": 55},

    # ===== East Asia =====
    {"code": "cn", "name": "China",          "region": "Asia",          "population":1410000000, "gdp_pc": 23000, "life_expectancy": 77, "infant_mortality":  6, "literacy": 97, "gini": 38, "hdi": 0.77, "urban_pct": 64, "primary_religion": "None",           "primary_language": "Mandarin",   "capital": "Beijing",      "currency": "Yuan",          "war_freq": 0.005,"disaster_freq": 0.06, "crime_rate": 0.20, "corruption": 55, "safe_water_pct": 96, "health_services_pct": 95},
    {"code": "jp", "name": "Japan",          "region": "Asia",          "population": 124000000, "gdp_pc": 49000, "life_expectancy": 84, "infant_mortality":  2, "literacy": 99, "gini": 33, "hdi": 0.92, "urban_pct": 92, "primary_religion": "Shinto",         "primary_language": "Japanese",   "capital": "Tokyo",        "currency": "Yen",           "war_freq": 0.001,"disaster_freq": 0.10, "crime_rate": 0.10, "corruption": 27, "safe_water_pct": 100,"health_services_pct": 100},
    {"code": "kr", "name": "South Korea",    "region": "Asia",          "population":  52000000, "gdp_pc": 50000, "life_expectancy": 83, "infant_mortality":  3, "literacy": 98, "gini": 31, "hdi": 0.93, "urban_pct": 81, "primary_religion": "None",           "primary_language": "Korean",     "capital": "Seoul",        "currency": "Won",           "war_freq": 0.005,"disaster_freq": 0.04, "crime_rate": 0.15, "corruption": 38, "safe_water_pct": 100,"health_services_pct": 99},
    {"code": "th", "name": "Thailand",       "region": "Asia",          "population":  70000000, "gdp_pc": 19000, "life_expectancy": 77, "infant_mortality":  7, "literacy": 94, "gini": 35, "hdi": 0.80, "urban_pct": 51, "primary_religion": "Buddhism",       "primary_language": "Thai",       "capital": "Bangkok",      "currency": "Baht",          "war_freq": 0.01, "disaster_freq": 0.06, "crime_rate": 0.30, "corruption": 64, "safe_water_pct": 100,"health_services_pct": 95},
    {"code": "vn", "name": "Vietnam",        "region": "Asia",          "population":  98000000, "gdp_pc": 11500, "life_expectancy": 75, "infant_mortality": 16, "literacy": 95, "gini": 37, "hdi": 0.70, "urban_pct": 38, "primary_religion": "Buddhism",       "primary_language": "Vietnamese", "capital": "Hanoi",        "currency": "Dong",          "war_freq": 0.005,"disaster_freq": 0.08, "crime_rate": 0.20, "corruption": 60, "safe_water_pct": 95, "health_services_pct": 87},
    {"code": "id", "name": "Indonesia",      "region": "Asia",          "population": 277000000, "gdp_pc": 14000, "life_expectancy": 71, "infant_mortality": 19, "literacy": 96, "gini": 38, "hdi": 0.71, "urban_pct": 57, "primary_religion": "Islam",          "primary_language": "Indonesian", "capital": "Jakarta",      "currency": "Rupiah",        "war_freq": 0.005,"disaster_freq": 0.12, "crime_rate": 0.30, "corruption": 66, "safe_water_pct": 93, "health_services_pct": 85},
    {"code": "ph", "name": "Philippines",    "region": "Asia",          "population": 116000000, "gdp_pc": 10000, "life_expectancy": 71, "infant_mortality": 21, "literacy": 96, "gini": 42, "hdi": 0.70, "urban_pct": 47, "primary_religion": "Christianity",   "primary_language": "Filipino",   "capital": "Manila",       "currency": "Peso",          "war_freq": 0.02, "disaster_freq": 0.18, "crime_rate": 0.45, "corruption": 67, "safe_water_pct": 97, "health_services_pct": 80},

    # ===== Europe =====
    {"code": "gb", "name": "United Kingdom", "region": "Europe",        "population":  68000000, "gdp_pc": 51000, "life_expectancy": 81, "infant_mortality":  4, "literacy": 99, "gini": 35, "hdi": 0.93, "urban_pct": 84, "primary_religion": "Christianity",   "primary_language": "English",    "capital": "London",       "currency": "Pound sterling","war_freq": 0.005,"disaster_freq": 0.02, "crime_rate": 0.35, "corruption": 27, "safe_water_pct": 100,"health_services_pct": 100},
    {"code": "fr", "name": "France",         "region": "Europe",        "population":  68000000, "gdp_pc": 53000, "life_expectancy": 83, "infant_mortality":  3, "literacy": 99, "gini": 32, "hdi": 0.90, "urban_pct": 82, "primary_religion": "Christianity",   "primary_language": "French",     "capital": "Paris",        "currency": "Euro",          "war_freq": 0.005,"disaster_freq": 0.02, "crime_rate": 0.30, "corruption": 28, "safe_water_pct": 100,"health_services_pct": 100},
    {"code": "de", "name": "Germany",        "region": "Europe",        "population":  84000000, "gdp_pc": 57000, "life_expectancy": 81, "infant_mortality":  3, "literacy": 99, "gini": 31, "hdi": 0.94, "urban_pct": 78, "primary_religion": "Christianity",   "primary_language": "German",     "capital": "Berlin",       "currency": "Euro",          "war_freq": 0.005,"disaster_freq": 0.02, "crime_rate": 0.25, "corruption": 21, "safe_water_pct": 100,"health_services_pct": 100},
    {"code": "it", "name": "Italy",          "region": "Europe",        "population":  59000000, "gdp_pc": 49000, "life_expectancy": 83, "infant_mortality":  3, "literacy": 99, "gini": 35, "hdi": 0.90, "urban_pct": 71, "primary_religion": "Christianity",   "primary_language": "Italian",    "capital": "Rome",         "currency": "Euro",          "war_freq": 0.005,"disaster_freq": 0.04, "crime_rate": 0.30, "corruption": 44, "safe_water_pct": 100,"health_services_pct": 100},
    {"code": "es", "name": "Spain",          "region": "Europe",        "population":  47000000, "gdp_pc": 45000, "life_expectancy": 83, "infant_mortality":  3, "literacy": 99, "gini": 33, "hdi": 0.91, "urban_pct": 81, "primary_religion": "Christianity",   "primary_language": "Spanish",    "capital": "Madrid",       "currency": "Euro",          "war_freq": 0.005,"disaster_freq": 0.02, "crime_rate": 0.30, "corruption": 40, "safe_water_pct": 100,"health_services_pct": 100},
    {"code": "se", "name": "Sweden",         "region": "Europe",        "population":  10500000, "gdp_pc": 60000, "life_expectancy": 83, "infant_mortality":  2, "literacy": 99, "gini": 28, "hdi": 0.95, "urban_pct": 88, "primary_religion": "Christianity",   "primary_language": "Swedish",    "capital": "Stockholm",    "currency": "Krona",         "war_freq": 0.001,"disaster_freq": 0.01, "crime_rate": 0.25, "corruption": 12, "safe_water_pct": 100,"health_services_pct": 100},
    {"code": "no", "name": "Norway",         "region": "Europe",        "population":   5500000, "gdp_pc": 80000, "life_expectancy": 83, "infant_mortality":  2, "literacy": 99, "gini": 27, "hdi": 0.96, "urban_pct": 83, "primary_religion": "Christianity",   "primary_language": "Norwegian",  "capital": "Oslo",         "currency": "Krone",         "war_freq": 0.001,"disaster_freq": 0.01, "crime_rate": 0.20, "corruption": 16, "safe_water_pct": 100,"health_services_pct": 100},
    {"code": "fi", "name": "Finland",        "region": "Europe",        "population":   5500000, "gdp_pc": 53000, "life_expectancy": 82, "infant_mortality":  2, "literacy": 99, "gini": 27, "hdi": 0.94, "urban_pct": 86, "primary_religion": "Christianity",   "primary_language": "Finnish",    "capital": "Helsinki",     "currency": "Euro",          "war_freq": 0.001,"disaster_freq": 0.01, "crime_rate": 0.20, "corruption": 12, "safe_water_pct": 100,"health_services_pct": 100},
    {"code": "ch", "name": "Switzerland",    "region": "Europe",        "population":   8800000, "gdp_pc": 84000, "life_expectancy": 84, "infant_mortality":  3, "literacy": 99, "gini": 33, "hdi": 0.96, "urban_pct": 74, "primary_religion": "Christianity",   "primary_language": "German",     "capital": "Bern",         "currency": "Swiss franc",   "war_freq": 0.001,"disaster_freq": 0.02, "crime_rate": 0.20, "corruption": 17, "safe_water_pct": 100,"health_services_pct": 100},
    {"code": "nl", "name": "Netherlands",    "region": "Europe",        "population":  17800000, "gdp_pc": 64000, "life_expectancy": 82, "infant_mortality":  3, "literacy": 99, "gini": 28, "hdi": 0.94, "urban_pct": 92, "primary_religion": "Christianity",   "primary_language": "Dutch",      "capital": "Amsterdam",    "currency": "Euro",          "war_freq": 0.001,"disaster_freq": 0.01, "crime_rate": 0.30, "corruption": 18, "safe_water_pct": 100,"health_services_pct": 100},
    {"code": "pl", "name": "Poland",         "region": "Europe",        "population":  38000000, "gdp_pc": 41000, "life_expectancy": 78, "infant_mortality":  4, "literacy": 99, "gini": 30, "hdi": 0.88, "urban_pct": 60, "primary_religion": "Christianity",   "primary_language": "Polish",     "capital": "Warsaw",       "currency": "Zloty",         "war_freq": 0.005,"disaster_freq": 0.02, "crime_rate": 0.25, "corruption": 45, "safe_water_pct": 100,"health_services_pct": 100},
    {"code": "ru", "name": "Russia",         "region": "Europe",        "population": 144000000, "gdp_pc": 30000, "life_expectancy": 71, "infant_mortality":  5, "literacy": 100,"gini": 36, "hdi": 0.82, "urban_pct": 75, "primary_religion": "Christianity",   "primary_language": "Russian",    "capital": "Moscow",       "currency": "Ruble",         "war_freq": 0.04, "disaster_freq": 0.03, "crime_rate": 0.45, "corruption": 72, "safe_water_pct": 97, "health_services_pct": 95},
    {"code": "ua", "name": "Ukraine",        "region": "Europe",        "population":  41000000, "gdp_pc": 13000, "life_expectancy": 72, "infant_mortality":  7, "literacy": 100,"gini": 26, "hdi": 0.77, "urban_pct": 70, "primary_religion": "Christianity",   "primary_language": "Ukrainian",  "capital": "Kyiv",         "currency": "Hryvnia",       "war_freq": 0.15, "disaster_freq": 0.02, "crime_rate": 0.35, "corruption": 67, "safe_water_pct": 96, "health_services_pct": 90},
    {"code": "gr", "name": "Greece",         "region": "Europe",        "population":  10500000, "gdp_pc": 36000, "life_expectancy": 82, "infant_mortality":  3, "literacy": 98, "gini": 33, "hdi": 0.89, "urban_pct": 80, "primary_religion": "Christianity",   "primary_language": "Greek",      "capital": "Athens",       "currency": "Euro",          "war_freq": 0.005,"disaster_freq": 0.04, "crime_rate": 0.25, "corruption": 49, "safe_water_pct": 100,"health_services_pct": 100},
    {"code": "ie", "name": "Ireland",        "region": "Europe",        "population":   5100000, "gdp_pc":102000, "life_expectancy": 82, "infant_mortality":  3, "literacy": 99, "gini": 31, "hdi": 0.95, "urban_pct": 64, "primary_religion": "Christianity",   "primary_language": "English",    "capital": "Dublin",       "currency": "Euro",          "war_freq": 0.001,"disaster_freq": 0.01, "crime_rate": 0.25, "corruption": 23, "safe_water_pct": 100,"health_services_pct": 100},

    # ===== North America =====
    {"code": "us", "name": "United States",  "region": "North America", "population": 333000000, "gdp_pc": 76000, "life_expectancy": 77, "infant_mortality":  5, "literacy": 99, "gini": 41, "hdi": 0.92, "urban_pct": 83, "primary_religion": "Christianity",   "primary_language": "English",    "capital": "Washington",   "currency": "Dollar",        "war_freq": 0.005,"disaster_freq": 0.05, "crime_rate": 0.45, "corruption": 33, "safe_water_pct": 100,"health_services_pct": 92},
    {"code": "ca", "name": "Canada",         "region": "North America", "population":  39000000, "gdp_pc": 58000, "life_expectancy": 82, "infant_mortality":  4, "literacy": 99, "gini": 33, "hdi": 0.94, "urban_pct": 82, "primary_religion": "Christianity",   "primary_language": "English",    "capital": "Ottawa",       "currency": "Dollar",        "war_freq": 0.001,"disaster_freq": 0.03, "crime_rate": 0.25, "corruption": 26, "safe_water_pct": 100,"health_services_pct": 100},
    {"code": "mx", "name": "Mexico",         "region": "North America", "population": 128000000, "gdp_pc": 21000, "life_expectancy": 75, "infant_mortality": 12, "literacy": 95, "gini": 45, "hdi": 0.78, "urban_pct": 81, "primary_religion": "Christianity",   "primary_language": "Spanish",    "capital": "Mexico City",  "currency": "Peso",          "war_freq": 0.005,"disaster_freq": 0.05, "crime_rate": 0.55, "corruption": 69, "safe_water_pct": 99, "health_services_pct": 90},

    # ===== Central America & Caribbean =====
    {"code": "gt", "name": "Guatemala",      "region": "Central America","population": 18000000, "gdp_pc":  9300, "life_expectancy": 72, "infant_mortality": 21, "literacy": 83, "gini": 48, "hdi": 0.63, "urban_pct": 52, "primary_religion": "Christianity",   "primary_language": "Spanish",    "capital": "Guatemala City","currency": "Quetzal",      "war_freq": 0.01, "disaster_freq": 0.07, "crime_rate": 0.65, "corruption": 75, "safe_water_pct": 95, "health_services_pct": 70},
    {"code": "cu", "name": "Cuba",           "region": "Caribbean",     "population":  11000000, "gdp_pc":  9500, "life_expectancy": 79, "infant_mortality":  4, "literacy": 100,"gini": 38, "hdi": 0.76, "urban_pct": 77, "primary_religion": "None",           "primary_language": "Spanish",    "capital": "Havana",       "currency": "Peso",          "war_freq": 0.005,"disaster_freq": 0.07, "crime_rate": 0.20, "corruption": 54, "safe_water_pct": 96, "health_services_pct": 100},
    {"code": "ht", "name": "Haiti",          "region": "Caribbean",     "population":  11500000, "gdp_pc":  3000, "life_expectancy": 64, "infant_mortality": 47, "literacy": 62, "gini": 41, "hdi": 0.54, "urban_pct": 58, "primary_religion": "Christianity",   "primary_language": "Creole",     "capital": "Port-au-Prince","currency": "Gourde",       "war_freq": 0.02, "disaster_freq": 0.20, "crime_rate": 0.65, "corruption": 80, "safe_water_pct": 65, "health_services_pct": 50},
    {"code": "do", "name": "Dominican Republic","region":"Caribbean",   "population":  11000000, "gdp_pc": 21000, "life_expectancy": 74, "infant_mortality": 24, "literacy": 95, "gini": 41, "hdi": 0.77, "urban_pct": 83, "primary_religion": "Christianity",   "primary_language": "Spanish",    "capital": "Santo Domingo","currency": "Peso",          "war_freq": 0.005,"disaster_freq": 0.06, "crime_rate": 0.50, "corruption": 65, "safe_water_pct": 97, "health_services_pct": 85},

    # ===== South America =====
    {"code": "br", "name": "Brazil",         "region": "South America", "population": 215000000, "gdp_pc": 18000, "life_expectancy": 76, "infant_mortality": 13, "literacy": 94, "gini": 53, "hdi": 0.75, "urban_pct": 87, "primary_religion": "Christianity",   "primary_language": "Portuguese", "capital": "Brasilia",     "currency": "Real",          "war_freq": 0.005,"disaster_freq": 0.04, "crime_rate": 0.55, "corruption": 62, "safe_water_pct": 98, "health_services_pct": 90},
    {"code": "ar", "name": "Argentina",      "region": "South America", "population":  46000000, "gdp_pc": 27000, "life_expectancy": 77, "infant_mortality":  9, "literacy": 99, "gini": 42, "hdi": 0.84, "urban_pct": 92, "primary_religion": "Christianity",   "primary_language": "Spanish",    "capital": "Buenos Aires", "currency": "Peso",          "war_freq": 0.001,"disaster_freq": 0.03, "crime_rate": 0.40, "corruption": 62, "safe_water_pct": 99, "health_services_pct": 95},
    {"code": "co", "name": "Colombia",       "region": "South America", "population":  52000000, "gdp_pc": 17000, "life_expectancy": 77, "infant_mortality": 12, "literacy": 95, "gini": 51, "hdi": 0.75, "urban_pct": 81, "primary_religion": "Christianity",   "primary_language": "Spanish",    "capital": "Bogota",       "currency": "Peso",          "war_freq": 0.04, "disaster_freq": 0.06, "crime_rate": 0.55, "corruption": 60, "safe_water_pct": 97, "health_services_pct": 85},
    {"code": "pe", "name": "Peru",           "region": "South America", "population":  34000000, "gdp_pc": 14000, "life_expectancy": 73, "infant_mortality": 10, "literacy": 94, "gini": 41, "hdi": 0.76, "urban_pct": 78, "primary_religion": "Christianity",   "primary_language": "Spanish",    "capital": "Lima",         "currency": "Sol",           "war_freq": 0.005,"disaster_freq": 0.07, "crime_rate": 0.55, "corruption": 64, "safe_water_pct": 91, "health_services_pct": 80},
    {"code": "ve", "name": "Venezuela",      "region": "South America", "population":  29000000, "gdp_pc": 16000, "life_expectancy": 73, "infant_mortality": 22, "literacy": 97, "gini": 45, "hdi": 0.70, "urban_pct": 88, "primary_religion": "Christianity",   "primary_language": "Spanish",    "capital": "Caracas",      "currency": "Bolivar",       "war_freq": 0.005,"disaster_freq": 0.04, "crime_rate": 0.75, "corruption": 86, "safe_water_pct": 95, "health_services_pct": 80},
    {"code": "cl", "name": "Chile",          "region": "South America", "population":  19500000, "gdp_pc": 30000, "life_expectancy": 80, "infant_mortality":  6, "literacy": 96, "gini": 44, "hdi": 0.85, "urban_pct": 88, "primary_religion": "Christianity",   "primary_language": "Spanish",    "capital": "Santiago",     "currency": "Peso",          "war_freq": 0.001,"disaster_freq": 0.06, "crime_rate": 0.35, "corruption": 33, "safe_water_pct": 100,"health_services_pct": 95},

    # ===== Oceania =====
    {"code": "au", "name": "Australia",      "region": "Oceania",       "population":  26000000, "gdp_pc": 60000, "life_expectancy": 84, "infant_mortality":  3, "literacy": 99, "gini": 34, "hdi": 0.95, "urban_pct": 87, "primary_religion": "Christianity",   "primary_language": "English",    "capital": "Canberra",     "currency": "Dollar",        "war_freq": 0.001,"disaster_freq": 0.05, "crime_rate": 0.30, "corruption": 25, "safe_water_pct": 100,"health_services_pct": 100},
    {"code": "nz", "name": "New Zealand",    "region": "Oceania",       "population":   5200000, "gdp_pc": 49000, "life_expectancy": 82, "infant_mortality":  4, "literacy": 99, "gini": 32, "hdi": 0.94, "urban_pct": 87, "primary_religion": "Christianity",   "primary_language": "English",    "capital": "Wellington",   "currency": "Dollar",        "war_freq": 0.001,"disaster_freq": 0.03, "crime_rate": 0.30, "corruption": 12, "safe_water_pct": 100,"health_services_pct": 100},
    {"code": "pg", "name": "Papua New Guinea","region":"Oceania",       "population":  10000000, "gdp_pc":  4400, "life_expectancy": 65, "infant_mortality": 36, "literacy": 64, "gini": 42, "hdi": 0.56, "urban_pct": 14, "primary_religion": "Christianity",   "primary_language": "English",    "capital": "Port Moresby", "currency": "Kina",          "war_freq": 0.01, "disaster_freq": 0.07, "crime_rate": 0.65, "corruption": 70, "safe_water_pct": 47, "health_services_pct": 60},
]


# Curated job catalogue. ~30 representative jobs that span the original game's
# range — unskilled labor up through executive/professional. min_education
# values: 0=none, 1=primary, 2=secondary, 3=vocational, 4=university.
JOBS: list[dict] = [
    {"name": "subsistence farmer",      "min_education": 0, "min_intelligence":  0, "min_age": 12, "max_age": 70, "salary_low":   500, "salary_high":   2500, "urban_only": False},
    {"name": "fisherman",               "min_education": 0, "min_intelligence":  0, "min_age": 14, "max_age": 65, "salary_low":  1000, "salary_high":   4000, "urban_only": False},
    {"name": "street vendor",           "min_education": 0, "min_intelligence": 20, "min_age": 12, "max_age": 70, "salary_low":   600, "salary_high":   3500, "urban_only": True},
    {"name": "factory worker",          "min_education": 1, "min_intelligence": 25, "min_age": 16, "max_age": 60, "salary_low":  3000, "salary_high":  12000, "urban_only": True},
    {"name": "construction worker",     "min_education": 1, "min_intelligence": 25, "min_age": 16, "max_age": 60, "salary_low":  4000, "salary_high":  14000, "urban_only": False},
    {"name": "domestic servant",        "min_education": 0, "min_intelligence": 20, "min_age": 14, "max_age": 65, "salary_low":  1500, "salary_high":   6000, "urban_only": True},
    {"name": "taxi driver",             "min_education": 1, "min_intelligence": 30, "min_age": 18, "max_age": 65, "salary_low":  4000, "salary_high":  15000, "urban_only": True},
    {"name": "shopkeeper",              "min_education": 2, "min_intelligence": 35, "min_age": 18, "max_age": 70, "salary_low":  6000, "salary_high":  25000, "urban_only": True},
    {"name": "waiter",                  "min_education": 1, "min_intelligence": 30, "min_age": 16, "max_age": 50, "salary_low":  3000, "salary_high":  18000, "urban_only": True},
    {"name": "soldier",                 "min_education": 1, "min_intelligence": 35, "min_age": 18, "max_age": 45, "salary_low":  6000, "salary_high":  30000, "urban_only": False},
    {"name": "police officer",          "min_education": 2, "min_intelligence": 40, "min_age": 21, "max_age": 55, "salary_low":  8000, "salary_high":  35000, "urban_only": False},
    {"name": "nurse",                   "min_education": 3, "min_intelligence": 55, "min_age": 21, "max_age": 65, "salary_low": 12000, "salary_high":  45000, "urban_only": False},
    {"name": "primary school teacher",  "min_education": 4, "min_intelligence": 55, "min_age": 22, "max_age": 65, "salary_low": 10000, "salary_high":  35000, "urban_only": False},
    {"name": "secondary school teacher","min_education": 4, "min_intelligence": 60, "min_age": 24, "max_age": 65, "salary_low": 14000, "salary_high":  45000, "urban_only": False},
    {"name": "accountant",              "min_education": 4, "min_intelligence": 65, "min_age": 22, "max_age": 65, "salary_low": 18000, "salary_high":  80000, "urban_only": True},
    {"name": "civil engineer",          "min_education": 4, "min_intelligence": 70, "min_age": 23, "max_age": 65, "salary_low": 25000, "salary_high":  95000, "urban_only": False},
    {"name": "software developer",      "min_education": 4, "min_intelligence": 70, "min_age": 22, "max_age": 65, "salary_low": 30000, "salary_high": 140000, "urban_only": True},
    {"name": "lawyer",                  "min_education": 4, "min_intelligence": 75, "min_age": 25, "max_age": 70, "salary_low": 30000, "salary_high": 200000, "urban_only": True},
    {"name": "doctor",                  "min_education": 4, "min_intelligence": 80, "min_age": 26, "max_age": 70, "salary_low": 40000, "salary_high": 250000, "urban_only": False},
    {"name": "surgeon",                 "min_education": 4, "min_intelligence": 85, "min_age": 30, "max_age": 65, "salary_low": 80000, "salary_high": 400000, "urban_only": True},
    {"name": "university professor",    "min_education": 4, "min_intelligence": 80, "min_age": 28, "max_age": 70, "salary_low": 35000, "salary_high": 130000, "urban_only": True},
    {"name": "journalist",              "min_education": 4, "min_intelligence": 65, "min_age": 22, "max_age": 65, "salary_low": 14000, "salary_high":  70000, "urban_only": True},
    {"name": "writer",                  "min_education": 2, "min_intelligence": 60, "min_age": 18, "max_age": 80, "salary_low":     0, "salary_high":  90000, "urban_only": False},
    {"name": "musician",                "min_education": 0, "min_intelligence": 30, "min_age": 14, "max_age": 70, "salary_low":     0, "salary_high":  80000, "urban_only": False},
    {"name": "professional athlete",    "min_education": 1, "min_intelligence": 30, "min_age": 16, "max_age": 38, "salary_low":     0, "salary_high": 500000, "urban_only": False},
    {"name": "small business owner",    "min_education": 2, "min_intelligence": 50, "min_age": 22, "max_age": 70, "salary_low":  8000, "salary_high":  90000, "urban_only": False},
    {"name": "civil servant",           "min_education": 3, "min_intelligence": 55, "min_age": 22, "max_age": 65, "salary_low": 10000, "salary_high":  60000, "urban_only": True},
    {"name": "senior government official","min_education":4,"min_intelligence": 70, "min_age": 35, "max_age": 70, "salary_low": 30000, "salary_high": 120000, "urban_only": True},
    {"name": "executive manager",       "min_education": 4, "min_intelligence": 75, "min_age": 30, "max_age": 65, "salary_low": 60000, "salary_high": 350000, "urban_only": True},
    {"name": "religious leader",        "min_education": 2, "min_intelligence": 50, "min_age": 25, "max_age": 80, "salary_low":  3000, "salary_high":  35000, "urban_only": False},
]


# Investment options.
INVESTMENTS: list[dict] = [
    {"name": "savings account",      "annual_return_low":  0.01, "annual_return_high": 0.04, "risk": 0.0,  "min_amount":    100},
    {"name": "government bonds",     "annual_return_low":  0.02, "annual_return_high": 0.06, "risk": 0.05, "min_amount":   1000},
    {"name": "corporate bonds",      "annual_return_low":  0.03, "annual_return_high": 0.10, "risk": 0.15, "min_amount":   2000},
    {"name": "low-risk stock fund",  "annual_return_low": -0.05, "annual_return_high": 0.12, "risk": 0.25, "min_amount":   1000},
    {"name": "high-risk stock",      "annual_return_low": -0.40, "annual_return_high": 0.60, "risk": 0.55, "min_amount":   2500},
    {"name": "real estate",          "annual_return_low": -0.05, "annual_return_high": 0.15, "risk": 0.30, "min_amount":  20000},
    {"name": "small business",       "annual_return_low": -0.50, "annual_return_high": 0.80, "risk": 0.60, "min_amount":   5000},
]


# Loan products.
LOANS: list[dict] = [
    {"name": "family loan",       "max_amount":     5000, "interest_rate": 0.00, "max_years":  5},
    {"name": "personal loan",     "max_amount":    25000, "interest_rate": 0.12, "max_years":  7},
    {"name": "education loan",    "max_amount":   100000, "interest_rate": 0.05, "max_years": 20},
    {"name": "car loan",          "max_amount":    40000, "interest_rate": 0.08, "max_years":  5},
    {"name": "mortgage",          "max_amount":   500000, "interest_rate": 0.06, "max_years": 30},
    {"name": "small business loan","max_amount":  150000, "interest_rate": 0.10, "max_years": 10},
]
