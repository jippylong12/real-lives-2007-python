"""
Discretionary spending: lifestyle purchases and recurring subscriptions (#66, #112).

The career system gives the player a salary; the investment system lets
them park money; the loan system lets them borrow. This module provides
a deep catalog of meaningful purchases across 8 categories — housing,
vehicles, lifestyle, tech, health, subscriptions, education, and
charity — each with a cost, an effect on attributes / happiness /
family wealth, and an optional recurring subscription.

Big-ticket purchases are one-time and added to ``character.purchases``
for the death retrospective. Subscriptions live in
``character.subscriptions`` and the yearly income tick in
:mod:`careers` deducts their costs.

Country-relative pricing
------------------------
A "house" in Norway costs vastly more than a "house" in rural Niger.
Each purchase declares a USD-baseline cost and is scaled by
``country.gdp_pc / 50000`` (the same scale the careers module uses for
salaries) so the relative affordability stays meaningful across the
193 countries the binary covers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .character import Character
from .world import Country


@dataclass(frozen=True)
class Purchase:
    """One row in the discretionary-spending registry."""
    key: str                       # stable identifier (used by API + tests)
    name: str                      # display label
    category: str                  # housing|vehicles|lifestyle|tech|health|subscription|education|charity
    description: str
    base_cost: int                 # USD baseline; scaled by country GDP
    deltas: dict[str, int] = field(default_factory=dict)
    happiness_delta: int = 0
    family_wealth_delta: int = 0
    one_time: bool = True          # if False, can be bought again
    monthly_cost: int = 0          # subscriptions only
    requires_no_existing: str | None = None  # block if character has this purchase key
    requires_min_age: int = 14
    min_health_services: int = 0   # gates premium services to good-healthcare countries


# ---------------------------------------------------------------------------
# Purchase catalog (#66, #112)
# ---------------------------------------------------------------------------
# ~250 items across 8 categories. Each purchase is a meaningful life
# decision with tiered costs and attribute effects. Prices are USD
# baselines scaled by country GDP.

def _p(key, name, cat, desc, cost, **kw):
    """Shorthand constructor to keep the registry readable."""
    return Purchase(key=key, name=name, category=cat, description=desc, base_cost=cost, **kw)


PURCHASES: list[Purchase] = [
    # =======================================================================
    # HOUSING — homes, furnishings, renovations, property
    # =======================================================================
    _p("house_studio", "Studio apartment", "housing",
       "Four walls and a hot plate. It's yours.", 35_000,
       family_wealth_delta=25_000, happiness_delta=5,
       requires_min_age=18, requires_no_existing="house_studio"),
    _p("house_small_apt", "Small apartment", "housing",
       "One bedroom, a kitchen that works, and enough space to breathe.", 55_000,
       family_wealth_delta=40_000, happiness_delta=7,
       requires_min_age=19, requires_no_existing="house_small_apt"),
    _p("house_starter", "Starter home", "housing",
       "A modest place to call your own. Major commitment, lasting impact.", 80_000,
       family_wealth_delta=60_000, happiness_delta=10, deltas={"conscience": +2},
       requires_min_age=21, requires_no_existing="house_starter"),
    _p("house_family", "Family home", "housing",
       "Bigger, nicer, in a better neighborhood. The kind of place a family grows up in.", 250_000,
       family_wealth_delta=200_000, happiness_delta=14, deltas={"conscience": +3, "appearance": +1},
       requires_min_age=25),
    _p("house_luxury", "Luxury home", "housing",
       "A statement of arrival. Marble floors, a view, and a sizable mortgage even if you pay cash.", 900_000,
       family_wealth_delta=750_000, happiness_delta=18, deltas={"appearance": +3, "happiness": +5},
       requires_min_age=30),
    _p("house_mansion", "Mansion", "housing",
       "Gates, grounds, guest houses. The kind of property that needs staff.", 3_500_000,
       family_wealth_delta=3_000_000, happiness_delta=22, deltas={"appearance": +5, "happiness": +8},
       requires_min_age=35),
    _p("house_country_estate", "Country estate", "housing",
       "Rolling acres, old stone, and the quiet that money buys.", 6_000_000,
       family_wealth_delta=5_000_000, happiness_delta=20, deltas={"wisdom": +3, "happiness": +6},
       requires_min_age=40),
    _p("house_penthouse", "City penthouse", "housing",
       "Top floor, floor-to-ceiling glass, a skyline that belongs to you.", 2_200_000,
       family_wealth_delta=1_800_000, happiness_delta=20, deltas={"appearance": +4, "happiness": +6},
       requires_min_age=30),
    _p("furn_basic", "Basic furniture set", "housing",
       "Everything you need to stop sitting on the floor.", 2_000,
       happiness_delta=3, requires_min_age=18, one_time=False),
    _p("furn_mid", "Quality furniture", "housing",
       "Solid wood, real upholstery, pieces that'll last.", 8_000,
       happiness_delta=5, deltas={"appearance": +1},
       requires_min_age=22, one_time=False),
    _p("furn_designer", "Designer furniture", "housing",
       "Mid-century modern, bespoke pieces. Your living room belongs in a magazine.", 35_000,
       happiness_delta=8, deltas={"appearance": +2, "artistic": +1},
       requires_min_age=28, one_time=False),
    _p("reno_kitchen_basic", "Kitchen renovation", "housing",
       "New countertops, fresh cabinets, appliances that actually work.", 12_000,
       happiness_delta=5, family_wealth_delta=8_000,
       requires_min_age=22, requires_no_existing="reno_kitchen_basic"),
    _p("reno_kitchen_luxury", "Dream kitchen", "housing",
       "Italian marble, a six-burner range, the kind of kitchen people photograph.", 45_000,
       happiness_delta=9, family_wealth_delta=30_000, deltas={"appearance": +1},
       requires_min_age=28, requires_no_existing="reno_kitchen_luxury"),
    _p("reno_bathroom", "Bathroom remodel", "housing",
       "Walk-in shower, heated floors, a space that feels like a spa.", 15_000,
       happiness_delta=5, family_wealth_delta=10_000,
       requires_min_age=22, requires_no_existing="reno_bathroom"),
    _p("home_garden", "Garden landscaping", "housing",
       "Flower beds, a patio, maybe a few fruit trees. The yard becomes somewhere you want to be.", 5_000,
       happiness_delta=4, deltas={"health": +1},
       requires_min_age=22, requires_no_existing="home_garden"),
    _p("home_pool", "Swimming pool", "housing",
       "The centerpiece of summer. Also a serious maintenance commitment.", 40_000,
       happiness_delta=10, family_wealth_delta=20_000, deltas={"health": +1, "endurance": +1},
       requires_min_age=28, requires_no_existing="home_pool"),
    _p("home_security", "Home security system", "housing",
       "Cameras, sensors, monitoring. Peace of mind.", 3_000,
       happiness_delta=2, requires_min_age=18, requires_no_existing="home_security"),
    _p("home_solar", "Solar panels", "housing",
       "Energy independence. The electric bill drops to nearly zero.", 18_000,
       happiness_delta=3, family_wealth_delta=12_000, deltas={"conscience": +3},
       requires_min_age=25, requires_no_existing="home_solar"),
    _p("home_smart", "Smart home system", "housing",
       "Voice-controlled lights, automated blinds, a thermostat that knows your schedule.", 4_000,
       happiness_delta=3, deltas={"intelligence": +1},
       requires_min_age=18, requires_no_existing="home_smart"),
    _p("home_workshop", "Home workshop", "housing",
       "A proper workbench, power tools, and space to build things.", 6_000,
       happiness_delta=4, deltas={"artistic": +2, "strength": +1},
       requires_min_age=20, requires_no_existing="home_workshop"),
    _p("home_library", "Home library", "housing",
       "Floor-to-ceiling bookshelves. A reading chair. Hundreds of books.", 8_000,
       happiness_delta=5, deltas={"intelligence": +2, "wisdom": +1},
       requires_min_age=20, requires_no_existing="home_library"),
    _p("home_office", "Dedicated home office", "housing",
       "Standing desk, proper lighting, a door that closes. Work from home without losing your mind.", 4_500,
       happiness_delta=3, deltas={"intelligence": +1},
       requires_min_age=20, requires_no_existing="home_office"),
    _p("home_theater", "Home theater", "housing",
       "Projector, surround sound, blackout curtains. Movie night will never be the same.", 12_000,
       happiness_delta=6, deltas={"artistic": +1},
       requires_min_age=22, requires_no_existing="home_theater"),
    _p("home_wine_cellar", "Wine cellar", "housing",
       "Temperature-controlled, properly racked. A collection that appreciates.", 15_000,
       happiness_delta=4, family_wealth_delta=8_000, deltas={"appearance": +1},
       requires_min_age=30, requires_no_existing="home_wine_cellar"),
    _p("home_sauna", "Home sauna", "housing",
       "Cedar-lined, dry heat. Recovery and relaxation on demand.", 8_000,
       happiness_delta=4, deltas={"health": +2, "endurance": +1},
       requires_min_age=25, requires_no_existing="home_sauna"),

    # =======================================================================
    # VEHICLES — cars, motorcycles, boats, specialty
    # =======================================================================
    _p("car_used", "Used car", "vehicles",
       "High mileage, some scratches. But it runs and it's cheap.", 5_000,
       happiness_delta=2, requires_min_age=17),
    _p("car_basic", "Reliable car", "vehicles",
       "Gets you around. A sensible daily driver.", 14_000,
       happiness_delta=4, requires_min_age=18),
    _p("car_electric", "Electric car", "vehicles",
       "Quiet, efficient, and the charging infrastructure is finally there.", 32_000,
       happiness_delta=6, deltas={"conscience": +2},
       requires_min_age=20),
    _p("car_sport_sedan", "Sport sedan", "vehicles",
       "Four doors, turbo engine. The responsible choice that still puts a grin on your face.", 38_000,
       happiness_delta=7, deltas={"appearance": +1},
       requires_min_age=22),
    _p("car_premium", "Premium car", "vehicles",
       "Comfortable, fast, and noticed. People look twice.", 55_000,
       happiness_delta=9, deltas={"appearance": +2},
       requires_min_age=25),
    _p("car_suv_luxury", "Luxury SUV", "vehicles",
       "Leather everything, seven seats, enough tech to land a plane.", 70_000,
       happiness_delta=10, deltas={"appearance": +2},
       requires_min_age=28),
    _p("car_sports", "Sports car", "vehicles",
       "Two seats, mid-engine, and a sound that turns heads for blocks.", 95_000,
       happiness_delta=14, deltas={"appearance": +3},
       requires_min_age=28),
    _p("car_luxury", "Luxury car", "vehicles",
       "A symbol. The kind of vehicle that makes valets pay attention.", 130_000,
       happiness_delta=15, deltas={"appearance": +4},
       requires_min_age=30),
    _p("car_supercar", "Supercar", "vehicles",
       "Carbon fiber, 600+ horsepower, and a price tag that makes accountants nervous.", 280_000,
       happiness_delta=20, deltas={"appearance": +5},
       requires_min_age=30),
    _p("car_hypercar", "Hypercar", "vehicles",
       "Limited production. Seven figures. The kind of car museums want to borrow.", 1_500_000,
       happiness_delta=25, deltas={"appearance": +6},
       requires_min_age=35),
    _p("car_classic", "Classic car restoration", "vehicles",
       "A vintage beauty brought back to life. Weekends in the garage, shows on Sundays.", 40_000,
       happiness_delta=8, deltas={"artistic": +2, "wisdom": +1},
       requires_min_age=30, one_time=False),
    _p("car_pickup", "Pickup truck", "vehicles",
       "Hauls anything. The bed has seen lumber, mulch, and furniture.", 28_000,
       happiness_delta=4, deltas={"strength": +1},
       requires_min_age=18),
    _p("motorcycle", "Motorcycle", "vehicles",
       "Wind, speed, and a hint of recklessness.", 8_000,
       happiness_delta=6, deltas={"endurance": +1},
       requires_min_age=18),
    _p("motorcycle_premium", "Premium motorcycle", "vehicles",
       "Italian engineering, leather saddlebags, and the open road.", 22_000,
       happiness_delta=9, deltas={"appearance": +2, "endurance": +1},
       requires_min_age=22),
    _p("scooter", "Scooter", "vehicles",
       "Perfect for the city. Parks anywhere, sips fuel.", 2_500,
       happiness_delta=2, requires_min_age=16),
    _p("bicycle_nice", "Quality bicycle", "vehicles",
       "Carbon frame, good components. Weekend rides become a real hobby.", 2_000,
       happiness_delta=3, deltas={"health": +1, "endurance": +2},
       requires_min_age=14),
    _p("ebike", "E-bike", "vehicles",
       "Pedal-assist for the commute. Arrive without sweating through your shirt.", 3_500,
       happiness_delta=3, deltas={"health": +1, "endurance": +1},
       requires_min_age=16),
    _p("boat_small", "Small boat", "vehicles",
       "A weekend cruiser. Lake days, fishing trips, sunset runs.", 25_000,
       happiness_delta=8, deltas={"endurance": +1},
       requires_min_age=25),
    _p("boat_sailboat", "Sailboat", "vehicles",
       "Canvas, rope, and the patience to read the wind.", 60_000,
       happiness_delta=10, deltas={"wisdom": +2, "endurance": +2},
       requires_min_age=28),
    _p("boat_yacht", "Yacht", "vehicles",
       "Multiple cabins, a flybridge, and a crew. Harbor fees alone cost more than most cars.", 500_000,
       happiness_delta=18, deltas={"appearance": +4},
       requires_min_age=35),
    _p("rv_camper", "RV / Camper van", "vehicles",
       "Home on wheels. National parks, back roads, and no hotel reservations.", 45_000,
       happiness_delta=8, deltas={"wisdom": +2},
       requires_min_age=22),
    _p("jet_ski", "Jet ski", "vehicles",
       "Fast, loud, and exactly as fun as it looks.", 12_000,
       happiness_delta=5, deltas={"endurance": +1},
       requires_min_age=18),
    _p("atv", "ATV / four-wheeler", "vehicles",
       "Mud, trails, and the kind of fun that requires a helmet.", 8_000,
       happiness_delta=4, deltas={"endurance": +1, "strength": +1},
       requires_min_age=16),

    # =======================================================================
    # LIFESTYLE — vacations, dining, entertainment, clothing, experiences
    # =======================================================================
    _p("vacation_local", "Domestic vacation", "lifestyle",
       "A week away. Familiar food, no jet lag.", 800,
       happiness_delta=6, deltas={"wisdom": +1},
       one_time=False, requires_min_age=16),
    _p("vacation_international", "International vacation", "lifestyle",
       "A passport stamp and a sense of how big the world is.", 4_500,
       happiness_delta=12, deltas={"wisdom": +3},
       one_time=False, requires_min_age=18),
    _p("vacation_luxury", "Luxury holiday", "lifestyle",
       "The kind of trip you'll talk about for years. Five-star everything.", 20_000,
       happiness_delta=18, deltas={"wisdom": +4, "appearance": +1},
       one_time=False, requires_min_age=22),
    _p("vacation_backpacking", "Backpacking trip", "lifestyle",
       "Hostels, trains, street food, and a stuffed backpack. Three weeks of beautiful chaos.", 1_500,
       happiness_delta=8, deltas={"wisdom": +3, "endurance": +2},
       one_time=False, requires_min_age=18),
    _p("vacation_cruise", "World cruise", "lifestyle",
       "Three months on a ship. Dozens of ports. A floating hotel with a schedule.", 25_000,
       happiness_delta=20, deltas={"wisdom": +5},
       one_time=False, requires_min_age=30),
    _p("vacation_safari", "Safari expedition", "lifestyle",
       "Dawn drives through the savanna. Lions at fifty yards. A sunrise you'll never forget.", 8_000,
       happiness_delta=14, deltas={"wisdom": +3},
       one_time=False, requires_min_age=20),
    _p("vacation_ski", "Ski vacation", "lifestyle",
       "Fresh powder, mountain air, and hot chocolate by the fire.", 3_500,
       happiness_delta=8, deltas={"endurance": +1, "health": +1},
       one_time=False, requires_min_age=16),
    _p("vacation_beach", "Beach resort", "lifestyle",
       "White sand, turquoise water, all-inclusive. Do nothing for a week.", 3_000,
       happiness_delta=9, deltas={"health": +1},
       one_time=False, requires_min_age=18),
    _p("vacation_cultural", "Cultural immersion trip", "lifestyle",
       "Language school, homestay, local markets. Live somewhere instead of just visiting.", 5_000,
       happiness_delta=10, deltas={"wisdom": +4, "intelligence": +1},
       one_time=False, requires_min_age=18),
    _p("vacation_road_trip", "Road trip", "lifestyle",
       "Playlist, snacks, and the open road. No itinerary, just vibes.", 1_200,
       happiness_delta=6, deltas={"wisdom": +1},
       one_time=False, requires_min_age=18),
    _p("dining_fine", "Fine dining experience", "lifestyle",
       "Tasting menu, wine pairing, and a bill that makes you blink.", 500,
       happiness_delta=4, deltas={"wisdom": +1},
       one_time=False, requires_min_age=18),
    _p("dining_cooking_class", "Cooking class", "lifestyle",
       "Learn to make pasta from scratch, sushi, pastry — whatever you've always wanted to nail.", 300,
       happiness_delta=3, deltas={"intelligence": +1, "artistic": +1},
       one_time=False, requires_min_age=16),
    _p("dining_wine_tasting", "Wine tasting tour", "lifestyle",
       "Vineyards, barrel rooms, and learning the difference between notes of cherry and leather.", 400,
       happiness_delta=4, deltas={"wisdom": +1},
       one_time=False, requires_min_age=21),
    _p("clothing_wardrobe", "Wardrobe upgrade", "lifestyle",
       "Out with the old. New basics, a good jacket, shoes that fit.", 1_500,
       happiness_delta=4, deltas={"appearance": +2},
       one_time=False, requires_min_age=16),
    _p("clothing_designer", "Designer outfit", "lifestyle",
       "A single outfit that costs more than most people's entire closet.", 5_000,
       happiness_delta=6, deltas={"appearance": +3},
       one_time=False, requires_min_age=20),
    _p("clothing_tailor", "Custom tailored suit", "lifestyle",
       "Measured, cut, and stitched for you alone. The fit changes everything.", 3_000,
       happiness_delta=5, deltas={"appearance": +3},
       one_time=False, requires_min_age=22),
    _p("jewelry_modest", "Nice jewelry", "lifestyle",
       "A quality watch, a necklace, something that catches the light.", 1_200,
       happiness_delta=3, deltas={"appearance": +1},
       one_time=False, requires_min_age=18),
    _p("jewelry_luxury", "Luxury watch", "lifestyle",
       "Swiss movement, sapphire crystal. The kind of watch you pass down.", 15_000,
       happiness_delta=7, deltas={"appearance": +3},
       requires_min_age=25),
    _p("jewelry_diamond", "Diamond jewelry", "lifestyle",
       "A serious stone. Engagement ring, anniversary present, or just because.", 25_000,
       happiness_delta=8, deltas={"appearance": +3},
       one_time=False, requires_min_age=25),
    _p("concert", "Concert tickets", "lifestyle",
       "Front row, loud speakers, and a night you'll always remember.", 200,
       happiness_delta=5, deltas={"artistic": +1},
       one_time=False, requires_min_age=14),
    _p("festival", "Music festival", "lifestyle",
       "Three days, multiple stages, camping. You'll need a week to recover.", 600,
       happiness_delta=8, deltas={"artistic": +1, "endurance": +1},
       one_time=False, requires_min_age=16),
    _p("sports_tickets", "Sports season tickets", "lifestyle",
       "Every home game, your seat, your section. Part of the community.", 3_000,
       happiness_delta=6, one_time=False, requires_min_age=16),
    _p("theater_show", "Broadway / theater show", "lifestyle",
       "Live performance, orchestral pit, a story told in real time.", 300,
       happiness_delta=4, deltas={"artistic": +2, "wisdom": +1},
       one_time=False, requires_min_age=14),
    _p("theme_park", "Theme park pass", "lifestyle",
       "Annual access to rides, shows, and childhood nostalgia.", 500,
       happiness_delta=5, one_time=False, requires_min_age=10),
    _p("skydiving", "Skydiving experience", "lifestyle",
       "Thirteen thousand feet. Sixty seconds of freefall. Perspective adjustment.", 350,
       happiness_delta=8, deltas={"endurance": +1, "wisdom": +1},
       one_time=False, requires_min_age=18),
    _p("scuba_cert", "Scuba diving certification", "lifestyle",
       "Open water cert, reef dives, and a world beneath the surface.", 1_200,
       happiness_delta=6, deltas={"endurance": +2, "wisdom": +1},
       requires_min_age=16, requires_no_existing="scuba_cert"),
    _p("spa_weekend", "Spa weekend", "lifestyle",
       "Massages, hot springs, silence. Walk out feeling five years younger.", 800,
       happiness_delta=6, deltas={"health": +1},
       one_time=False, requires_min_age=18),
    _p("romantic_getaway", "Romantic getaway", "lifestyle",
       "A cabin, a coastline, or a city you've both been meaning to visit.", 2_000,
       happiness_delta=8, one_time=False, requires_min_age=18),
    _p("party_host", "Throw a big party", "lifestyle",
       "Catering, music, decorations. The kind of night people talk about for months.", 3_000,
       happiness_delta=7, deltas={"appearance": +1},
       one_time=False, requires_min_age=18),
    _p("wedding_vow_renewal", "Vow renewal ceremony", "lifestyle",
       "Recommit. Dress up. Celebrate what lasted.", 8_000,
       happiness_delta=10, deltas={"conscience": +2},
       one_time=False, requires_min_age=30),
    _p("tattoo", "Tattoo", "lifestyle",
       "Permanent ink. A design that means something — or just looks good.", 300,
       happiness_delta=2, deltas={"appearance": +1, "artistic": +1},
       one_time=False, requires_min_age=18),
    _p("personal_shopper", "Personal shopping spree", "lifestyle",
       "A professional stylist, a day at high-end stores, and bags you can barely carry.", 4_000,
       happiness_delta=6, deltas={"appearance": +3},
       one_time=False, requires_min_age=22),
    _p("perfume_cologne", "Signature fragrance", "lifestyle",
       "A scent people associate with you. Quality that lasts.", 250,
       happiness_delta=2, deltas={"appearance": +1},
       one_time=False, requires_min_age=16),
    _p("art_purchase", "Original artwork", "lifestyle",
       "A painting, sculpture, or print from an artist you admire. The wall deserved better.", 2_500,
       happiness_delta=4, deltas={"artistic": +2},
       family_wealth_delta=1_500, one_time=False, requires_min_age=22),
    _p("art_commission", "Commission a portrait", "lifestyle",
       "Sit for a painter. Own a likeness that outlasts a photograph.", 5_000,
       happiness_delta=5, deltas={"artistic": +1, "appearance": +1},
       one_time=False, requires_min_age=25),

    # =======================================================================
    # TECH — electronics, gadgets, gaming
    # =======================================================================
    _p("phone_basic", "Smartphone", "tech",
       "A decent phone. Does everything you need.", 400,
       happiness_delta=2, requires_min_age=12),
    _p("phone_flagship", "Flagship phone", "tech",
       "Best camera, fastest chip, the one everyone reviews.", 1_200,
       happiness_delta=4, deltas={"appearance": +1},
       requires_min_age=14),
    _p("laptop_basic", "Laptop", "tech",
       "Portable, reliable, gets work done.", 800,
       happiness_delta=2, deltas={"intelligence": +1},
       requires_min_age=14),
    _p("laptop_pro", "Professional laptop", "tech",
       "Enough power for video editing, development, or serious spreadsheets.", 2_500,
       happiness_delta=4, deltas={"intelligence": +2},
       requires_min_age=18),
    _p("desktop_gaming", "Gaming PC", "tech",
       "RGB lights, liquid cooling, and a GPU that costs more than the monitor.", 2_000,
       happiness_delta=6, deltas={"intelligence": +1},
       requires_min_age=14, requires_no_existing="desktop_gaming"),
    _p("console", "Gaming console", "tech",
       "The latest generation. Couch gaming, online multiplayer, and a backlog you'll never clear.", 500,
       happiness_delta=4, requires_min_age=10),
    _p("vr_headset", "VR headset", "tech",
       "Step inside the game. Or just watch movies on a virtual 200-inch screen.", 600,
       happiness_delta=4, deltas={"intelligence": +1},
       requires_min_age=14, requires_no_existing="vr_headset"),
    _p("tablet", "Tablet", "tech",
       "Bigger screen for reading, drawing, or pretending you'll be productive on the couch.", 500,
       happiness_delta=2, requires_min_age=10),
    _p("smart_tv", "Smart TV", "tech",
       "65 inches, 4K, the kind of screen that makes movies feel like events.", 1_200,
       happiness_delta=4, requires_min_age=18, requires_no_existing="smart_tv"),
    _p("camera_basic", "Digital camera", "tech",
       "Interchangeable lenses, manual controls. Photography as a hobby starts here.", 800,
       happiness_delta=3, deltas={"artistic": +2},
       requires_min_age=14),
    _p("camera_pro", "Professional camera kit", "tech",
       "Full-frame sensor, fast glass, a bag that weighs more than a toddler.", 4_000,
       happiness_delta=5, deltas={"artistic": +4},
       requires_min_age=18),
    _p("drone", "Camera drone", "tech",
       "Aerial footage of everything. Beaches, mountains, your neighbor's yard (don't).", 1_000,
       happiness_delta=4, deltas={"artistic": +1, "intelligence": +1},
       requires_min_age=16),
    _p("ereader", "E-reader", "tech",
       "Carry a thousand books in your pocket. E-ink is easy on the eyes.", 200,
       happiness_delta=2, deltas={"intelligence": +1, "wisdom": +1},
       requires_min_age=10),
    _p("smartwatch", "Smartwatch", "tech",
       "Fitness tracking, notifications, and a silent alarm that taps your wrist.", 350,
       happiness_delta=2, deltas={"health": +1},
       requires_min_age=14),
    _p("headphones_pro", "Premium headphones", "tech",
       "Noise cancelling, spatial audio. Music the way the artist intended.", 400,
       happiness_delta=3, deltas={"artistic": +1},
       requires_min_age=12),
    _p("smart_speaker", "Smart speaker system", "tech",
       "Whole-home audio. Ask it anything, play anything, from any room.", 300,
       happiness_delta=2, requires_min_age=14),
    _p("3d_printer", "3D printer", "tech",
       "Print prototypes, replacement parts, or miniatures. The future arrived.", 600,
       happiness_delta=3, deltas={"intelligence": +2, "artistic": +1},
       requires_min_age=16, requires_no_existing="3d_printer"),
    _p("home_server", "Home server / NAS", "tech",
       "Your own cloud. Backups, media streaming, and full control of your data.", 800,
       happiness_delta=2, deltas={"intelligence": +2},
       requires_min_age=18, requires_no_existing="home_server"),
    _p("mechanical_keyboard", "Mechanical keyboard", "tech",
       "Clicky, tactile, and built to outlast three laptops.", 200,
       happiness_delta=1, requires_min_age=14),
    _p("projector", "Home projector", "tech",
       "Movie night goes from 55 inches to 120. The wall becomes a canvas.", 1_500,
       happiness_delta=4, requires_min_age=18),
    _p("telescope", "Telescope", "tech",
       "Saturn's rings, Jupiter's moons, nebulae. The night sky becomes personal.", 800,
       happiness_delta=3, deltas={"intelligence": +2, "wisdom": +1},
       requires_min_age=12),
    _p("robot_vacuum", "Robot vacuum", "tech",
       "It cleans while you sleep. The future's most boring and most useful invention.", 400,
       happiness_delta=1, requires_min_age=18),

    # =======================================================================
    # HEALTH & WELLNESS — fitness, beauty, medical elective, wellness
    # =======================================================================
    _p("home_gym", "Home gym equipment", "health",
       "Rack, bench, plates, dumbbells. No membership, no waiting.", 3_000,
       happiness_delta=4, deltas={"strength": +3, "endurance": +2, "health": +1},
       requires_min_age=16, requires_no_existing="home_gym"),
    _p("personal_trainer", "Personal trainer (10 sessions)", "health",
       "Someone who won't let you quit. Structured, intense, effective.", 1_500,
       happiness_delta=3, deltas={"strength": +2, "endurance": +2, "health": +1},
       one_time=False, requires_min_age=16),
    _p("nutrition_coach", "Nutrition coaching", "health",
       "Custom meal plan, macros tracked, supplements sorted.", 800,
       happiness_delta=2, deltas={"health": +2},
       requires_min_age=16, requires_no_existing="nutrition_coach"),
    _p("yoga_retreat", "Yoga retreat", "health",
       "A week of silence, stretching, and surprisingly difficult poses.", 2_000,
       happiness_delta=7, deltas={"health": +2, "endurance": +1, "wisdom": +1},
       one_time=False, requires_min_age=18),
    _p("meditation_retreat", "Meditation retreat", "health",
       "Ten days of silence. No phone, no talking, no distractions. Just you and your mind.", 1_500,
       happiness_delta=6, deltas={"wisdom": +3, "health": +1},
       one_time=False, requires_min_age=18),
    _p("spa_retreat", "Luxury spa retreat", "health",
       "A week of treatments, thermal baths, and meals designed by nutritionists.", 5_000,
       happiness_delta=10, deltas={"health": +2, "appearance": +1},
       one_time=False, requires_min_age=22),
    _p("dental_cosmetic", "Cosmetic dental work", "health",
       "Whitening, veneers, the kind of smile that opens doors.", 8_000,
       happiness_delta=5, deltas={"appearance": +3},
       requires_min_age=18, min_health_services=50),
    _p("lasik", "LASIK eye surgery", "health",
       "Wake up and see clearly. No glasses, no contacts, no squinting.", 5_000,
       happiness_delta=5, deltas={"health": +1},
       requires_min_age=21, min_health_services=60,
       requires_no_existing="lasik"),
    _p("cosmetic_minor", "Minor cosmetic procedure", "health",
       "Something small that's been bothering you for years. Fixed.", 4_000,
       happiness_delta=4, deltas={"appearance": +2},
       requires_min_age=21, min_health_services=60, one_time=False),
    _p("cosmetic_major", "Major cosmetic surgery", "health",
       "A significant change. Months of recovery, a different mirror.", 15_000,
       happiness_delta=6, deltas={"appearance": +4},
       requires_min_age=25, min_health_services=70, one_time=False),
    _p("marathon_training", "Marathon training program", "health",
       "Six months of structured runs building to 26.2 miles. You'll be a different person at the finish.", 500,
       happiness_delta=6, deltas={"endurance": +4, "health": +2, "strength": +1},
       one_time=False, requires_min_age=18),
    _p("martial_arts", "Martial arts training", "health",
       "Discipline, conditioning, and the confidence that comes from knowing how to handle yourself.", 1_000,
       happiness_delta=4, deltas={"strength": +2, "endurance": +2, "wisdom": +1},
       one_time=False, requires_min_age=14),
    _p("rock_climbing_gear", "Rock climbing gear", "health",
       "Harness, shoes, chalk bag. The gym wall first, then real rock.", 800,
       happiness_delta=4, deltas={"strength": +2, "endurance": +2},
       requires_min_age=14, requires_no_existing="rock_climbing_gear"),
    _p("surfboard", "Surfboard & wetsuit", "health",
       "Dawn patrol, salt water, and a skill that takes years to get right.", 600,
       happiness_delta=4, deltas={"endurance": +2, "strength": +1},
       requires_min_age=14, requires_no_existing="surfboard"),
    _p("standing_desk", "Standing desk", "health",
       "Adjustable height, cable management. Your back will thank you.", 600,
       happiness_delta=2, deltas={"health": +1},
       requires_min_age=18, requires_no_existing="standing_desk"),
    _p("massage_chair", "Massage chair", "health",
       "Shiatsu, heat, zero gravity recline. An indulgence that pays dividends.", 3_000,
       happiness_delta=3, deltas={"health": +1},
       requires_min_age=22, requires_no_existing="massage_chair"),
    _p("sleep_system", "Premium mattress & sleep system", "health",
       "The best mattress you can buy, blackout curtains, and a sleep tracker. A third of your life, upgraded.", 4_000,
       happiness_delta=4, deltas={"health": +2},
       requires_min_age=18, requires_no_existing="sleep_system"),
    _p("water_purifier", "Whole-home water purification", "health",
       "Clean water from every tap. No more filters, no more bottles.", 2_000,
       happiness_delta=1, deltas={"health": +1},
       requires_min_age=20, requires_no_existing="water_purifier"),
    _p("air_purifier", "Air purification system", "health",
       "HEPA filters in every room. Allergens, dust, and pollution — gone.", 1_000,
       happiness_delta=1, deltas={"health": +1},
       requires_min_age=18, requires_no_existing="air_purifier"),

    # =======================================================================
    # SUBSCRIPTIONS — recurring monthly costs
    # =======================================================================
    _p("sub_gym", "Gym membership", "subscription",
       "Stay strong. Slow physical decline.", 0,
       monthly_cost=50, requires_min_age=14,
       deltas={"strength": +2, "endurance": +1, "health": +1}),
    _p("sub_therapy", "Weekly therapy", "subscription",
       "Talk to someone. Sort yourself out.", 0,
       monthly_cost=200, requires_min_age=16,
       deltas={"happiness": +3, "wisdom": +1}),
    _p("sub_premium_health", "Premium healthcare plan", "subscription",
       "Concierge medicine — better doctors, faster appointments, premium drugs.", 0,
       monthly_cost=500, requires_min_age=18, min_health_services=60,
       deltas={"health": +2}),
    _p("sub_hobby", "Hobby & streaming", "subscription",
       "Books, music, streaming, the games you grew up with.", 0,
       monthly_cost=30, requires_min_age=10,
       deltas={"happiness": +1}),
    _p("sub_music", "Music streaming", "subscription",
       "Every song ever recorded. High fidelity, no ads, offline downloads.", 0,
       monthly_cost=12, requires_min_age=10,
       deltas={"happiness": +1, "artistic": +1}),
    _p("sub_news", "News & magazine subscription", "subscription",
       "Quality journalism from two or three publications you trust.", 0,
       monthly_cost=25, requires_min_age=14,
       deltas={"intelligence": +1, "wisdom": +1}),
    _p("sub_online_courses", "Online courses platform", "subscription",
       "Unlimited courses — programming, design, business, anything you're curious about.", 0,
       monthly_cost=40, requires_min_age=14,
       deltas={"intelligence": +2}),
    _p("sub_cloud_storage", "Cloud storage", "subscription",
       "2TB of encrypted cloud storage. Photos, documents, backups — always accessible.", 0,
       monthly_cost=10, requires_min_age=14,
       deltas={"intelligence": +1}),
    _p("sub_vpn", "VPN service", "subscription",
       "Encrypted browsing, no tracking, access from anywhere.", 0,
       monthly_cost=10, requires_min_age=14, deltas={}),
    _p("sub_meal_kit", "Meal kit delivery", "subscription",
       "Pre-portioned ingredients and recipes. Cooking without the grocery run.", 0,
       monthly_cost=120, requires_min_age=18,
       deltas={"health": +1}),
    _p("sub_wine_club", "Wine club", "subscription",
       "Two curated bottles a month. Tasting notes included.", 0,
       monthly_cost=60, requires_min_age=21,
       deltas={"wisdom": +1}),
    _p("sub_coffee", "Premium coffee subscription", "subscription",
       "Freshly roasted beans from a different origin every month.", 0,
       monthly_cost=25, requires_min_age=16,
       deltas={"happiness": +1}),
    _p("sub_language", "Language learning app", "subscription",
       "Daily practice. Fifteen minutes a day adds up to fluency.", 0,
       monthly_cost=15, requires_min_age=10,
       deltas={"intelligence": +1, "wisdom": +1}),
    _p("sub_cleaning", "Home cleaning service", "subscription",
       "Biweekly deep clean. Come home to a spotless house.", 0,
       monthly_cost=200, requires_min_age=22,
       deltas={"happiness": +2}),
    _p("sub_financial_advisor", "Financial advisor", "subscription",
       "Professional portfolio review, tax optimization, retirement planning.", 0,
       monthly_cost=250, requires_min_age=25,
       deltas={"wisdom": +1, "intelligence": +1}),
    _p("sub_fitness_app", "Fitness tracking app", "subscription",
       "Workout plans, progress photos, calorie tracking.", 0,
       monthly_cost=15, requires_min_age=14,
       deltas={"health": +1, "endurance": +1}),
    _p("sub_meditation", "Meditation app", "subscription",
       "Guided sessions, sleep stories, breathing exercises.", 0,
       monthly_cost=12, requires_min_age=14,
       deltas={"happiness": +1, "wisdom": +1}),
    _p("sub_pet_insurance", "Pet insurance", "subscription",
       "Coverage for vet bills, emergencies, and routine care.", 0,
       monthly_cost=45, requires_min_age=18,
       deltas={"conscience": +1}),
    _p("sub_identity_protection", "Identity protection service", "subscription",
       "Credit monitoring, dark web scans, identity theft insurance.", 0,
       monthly_cost=20, requires_min_age=18, deltas={}),
    _p("sub_audiobooks", "Audiobook subscription", "subscription",
       "Two books a month. Listen while commuting, exercising, or falling asleep.", 0,
       monthly_cost=15, requires_min_age=12,
       deltas={"intelligence": +1, "wisdom": +1}),
    _p("sub_personal_stylist", "Personal stylist service", "subscription",
       "Curated outfits delivered quarterly. Someone else figures out what looks good.", 0,
       monthly_cost=100, requires_min_age=20,
       deltas={"appearance": +2}),
    _p("sub_box_hobby", "Hobby box subscription", "subscription",
       "A surprise box each month — art supplies, puzzles, craft kits, whatever you picked.", 0,
       monthly_cost=35, requires_min_age=12,
       deltas={"artistic": +1, "happiness": +1}),
    _p("sub_coworking", "Coworking space membership", "subscription",
       "A desk, fast Wi-Fi, and people to nod at. Better than working from the kitchen.", 0,
       monthly_cost=200, requires_min_age=18,
       deltas={"intelligence": +1}),

    # =======================================================================
    # EDUCATION — courses, certifications, skills, personal development
    # =======================================================================
    _p("edu_online_cert", "Online certificate", "education",
       "A structured online program with a certificate at the end. Looks good on the resume.", 800,
       happiness_delta=3, deltas={"intelligence": +3},
       one_time=False, requires_min_age=16),
    _p("edu_professional_course", "Professional development course", "education",
       "An intensive week-long course in your field. Networking, case studies, and real credentials.", 3_000,
       happiness_delta=4, deltas={"intelligence": +4, "wisdom": +1},
       one_time=False, requires_min_age=22),
    _p("edu_workshop", "Workshop / seminar", "education",
       "A day with an expert. Hands-on, focused, immediately applicable.", 500,
       happiness_delta=2, deltas={"intelligence": +2},
       one_time=False, requires_min_age=16),
    _p("edu_books", "Book collection", "education",
       "Fifty books on subjects you care about. A personal library that matters.", 400,
       happiness_delta=3, deltas={"intelligence": +2, "wisdom": +2},
       one_time=False, requires_min_age=12),
    _p("edu_language_course", "In-person language course", "education",
       "Twelve weeks of immersive classes. Conversation practice, grammar drills, real progress.", 2_000,
       happiness_delta=4, deltas={"intelligence": +3, "wisdom": +2},
       one_time=False, requires_min_age=14),
    _p("edu_art_classes", "Art classes", "education",
       "Drawing, painting, sculpture — a semester of structured artistic development.", 1_200,
       happiness_delta=4, deltas={"artistic": +4, "wisdom": +1},
       one_time=False, requires_min_age=12),
    _p("edu_music_lessons", "Musical instrument lessons", "education",
       "Weekly lessons for a year. Scales, theory, and the satisfaction of slow mastery.", 2_000,
       happiness_delta=4, deltas={"musical": +4, "artistic": +1},
       one_time=False, requires_min_age=10),
    _p("edu_coding_bootcamp", "Coding bootcamp", "education",
       "Twelve weeks of intensive programming. Career change territory.", 12_000,
       happiness_delta=3, deltas={"intelligence": +5},
       requires_min_age=18, one_time=False),
    _p("edu_mba_prep", "MBA prep course", "education",
       "GMAT prep, application coaching, essay review. The on-ramp to business school.", 4_000,
       happiness_delta=2, deltas={"intelligence": +3, "wisdom": +1},
       requires_min_age=22),
    _p("edu_professional_cert", "Professional certification", "education",
       "CPA, PMP, AWS, whatever your field respects. Months of study, one exam, a real credential.", 2_500,
       happiness_delta=4, deltas={"intelligence": +4},
       one_time=False, requires_min_age=22),
    _p("edu_first_aid", "First aid / CPR certification", "education",
       "Learn to save a life. Two days that might matter more than anything.", 200,
       happiness_delta=2, deltas={"wisdom": +2, "conscience": +2},
       requires_min_age=14, requires_no_existing="edu_first_aid"),
    _p("edu_public_speaking", "Public speaking course", "education",
       "Overcome the fear. Learn to command a room. The skill that multiplies every other skill.", 1_500,
       happiness_delta=3, deltas={"intelligence": +2, "wisdom": +2, "appearance": +1},
       requires_min_age=18, requires_no_existing="edu_public_speaking"),
    _p("edu_financial_literacy", "Financial literacy course", "education",
       "Budgeting, investing, taxes, retirement. The class school should have taught.", 300,
       happiness_delta=2, deltas={"intelligence": +2, "wisdom": +2},
       requires_min_age=16, requires_no_existing="edu_financial_literacy"),
    _p("edu_creative_writing", "Creative writing workshop", "education",
       "Weekly workshop with feedback. Short stories, memoir, poetry — whatever you want to say.", 800,
       happiness_delta=3, deltas={"artistic": +3, "intelligence": +1, "wisdom": +1},
       one_time=False, requires_min_age=16),
    _p("edu_photography", "Photography course", "education",
       "Composition, lighting, post-processing. See the world differently.", 600,
       happiness_delta=3, deltas={"artistic": +3},
       requires_min_age=14, one_time=False),
    _p("edu_dance_lessons", "Dance lessons", "education",
       "Salsa, ballroom, or contemporary. Your body learns a new language.", 500,
       happiness_delta=4, deltas={"artistic": +2, "endurance": +1, "appearance": +1},
       one_time=False, requires_min_age=14),
    _p("edu_instrument_buy", "Musical instrument", "education",
       "A quality guitar, piano, violin, or whatever calls to you.", 1_500,
       happiness_delta=3, deltas={"musical": +2, "artistic": +1},
       requires_min_age=10, one_time=False),
    _p("edu_driving_course", "Advanced driving course", "education",
       "Defensive driving, track time, car control. Confidence behind the wheel.", 400,
       happiness_delta=2, deltas={"endurance": +1},
       requires_min_age=17, requires_no_existing="edu_driving_course"),
    _p("edu_wilderness_survival", "Wilderness survival course", "education",
       "Fire, shelter, navigation, foraging. A week in the woods with an instructor.", 1_200,
       happiness_delta=4, deltas={"endurance": +3, "wisdom": +2, "strength": +1},
       requires_min_age=16, one_time=False),
    _p("edu_chess_coaching", "Chess coaching", "education",
       "A grandmaster teaches you openings, endgames, and how to think ahead.", 600,
       happiness_delta=2, deltas={"intelligence": +3},
       requires_min_age=10, one_time=False),

    # =======================================================================
    # CHARITY & GIFTS — donations, family, community
    # =======================================================================
    _p("charity_small", "Donate to charity", "charity",
       "A meaningful gift to a cause you care about.", 500,
       happiness_delta=4, deltas={"conscience": +5, "wisdom": +1},
       one_time=False, requires_min_age=12),
    _p("charity_medium", "Substantial donation", "charity",
       "Enough to fund a specific project — a well, a scholarship, a year of meals.", 5_000,
       happiness_delta=6, deltas={"conscience": +8, "wisdom": +2},
       one_time=False, requires_min_age=20),
    _p("charity_major", "Major philanthropy", "charity",
       "The kind of donation that gets a wing named after you.", 50_000,
       happiness_delta=10, deltas={"conscience": +12, "wisdom": +3, "appearance": +1},
       one_time=False, requires_min_age=25),
    _p("charity_endowment", "Charitable endowment", "charity",
       "Establish a permanent fund. Your money works for the cause forever.", 200_000,
       happiness_delta=15, deltas={"conscience": +15, "wisdom": +4},
       one_time=False, requires_min_age=35),
    _p("gift_family", "Family gift", "charity",
       "Something nice for the people who raised you.", 2_000,
       happiness_delta=5, deltas={"conscience": +3},
       one_time=False, requires_min_age=14),
    _p("gift_spouse", "Gift for partner", "charity",
       "Jewelry, a trip, or something they mentioned once and forgot. You remembered.", 1_000,
       happiness_delta=5, deltas={"conscience": +2},
       one_time=False, requires_min_age=16),
    _p("gift_children", "Gift for children", "charity",
       "Toys, experiences, or savings bonds. Making their day is the point.", 500,
       happiness_delta=4, deltas={"conscience": +3},
       one_time=False, requires_min_age=20),
    _p("charity_community", "Community fundraiser", "charity",
       "Organize and fund a local event — food drive, neighborhood cleanup, school supply collection.", 1_000,
       happiness_delta=5, deltas={"conscience": +6, "wisdom": +1},
       one_time=False, requires_min_age=16),
    _p("charity_disaster", "Disaster relief donation", "charity",
       "When something terrible happens somewhere, you respond.", 2_000,
       happiness_delta=4, deltas={"conscience": +7},
       one_time=False, requires_min_age=18),
    _p("charity_environment", "Environmental cause donation", "charity",
       "Conservation, reforestation, ocean cleanup. The planet could use the help.", 1_500,
       happiness_delta=4, deltas={"conscience": +6, "wisdom": +1},
       one_time=False, requires_min_age=14),
    _p("charity_animal", "Animal shelter donation", "charity",
       "Help cover vet bills, food, and housing for animals that need it.", 500,
       happiness_delta=4, deltas={"conscience": +5},
       one_time=False, requires_min_age=10),
    _p("charity_sponsor", "Sponsor a child", "charity",
       "Monthly support for a child's education, healthcare, and basic needs.", 3_600,
       happiness_delta=6, deltas={"conscience": +8, "wisdom": +2},
       one_time=False, requires_min_age=20),
    _p("charity_habitat", "Habitat for Humanity build", "charity",
       "Donate time and money. Swing a hammer. Help build someone a home.", 2_000,
       happiness_delta=6, deltas={"conscience": +8, "strength": +1, "wisdom": +1},
       one_time=False, requires_min_age=18),
    _p("charity_volunteer_abroad", "Volunteer abroad trip", "charity",
       "Two weeks teaching, building, or providing medical support in a developing country.", 4_000,
       happiness_delta=8, deltas={"conscience": +10, "wisdom": +4},
       one_time=False, requires_min_age=18),
    _p("gift_housewarming", "Housewarming gift", "charity",
       "Champagne, a nice plant, something thoughtful for a friend's new place.", 200,
       happiness_delta=2, deltas={"conscience": +2},
       one_time=False, requires_min_age=18),
    _p("charity_scholarship", "Fund a scholarship", "charity",
       "Cover a year of tuition for someone who can't afford it. Change a trajectory.", 15_000,
       happiness_delta=8, deltas={"conscience": +10, "wisdom": +3},
       one_time=False, requires_min_age=30),
    _p("gift_mentor", "Mentorship program support", "charity",
       "Fund mentoring for young people in your community. Your experience, multiplied.", 1_000,
       happiness_delta=4, deltas={"conscience": +5, "wisdom": +2},
       one_time=False, requires_min_age=25),
    _p("pet_adopt", "Adopt a pet", "charity",
       "A rescue dog or cat. Adoption fees, first vet visit, supplies.", 500,
       happiness_delta=8, deltas={"conscience": +4, "happiness": +3},
       requires_min_age=16, one_time=False),
    _p("pet_supplies", "Premium pet supplies", "charity",
       "Orthopedic bed, quality food, toys, grooming. Your pet lives well.", 800,
       happiness_delta=2, deltas={"conscience": +1},
       one_time=False, requires_min_age=16),
    _p("gift_birthday_party", "Birthday party", "charity",
       "Rent a venue, hire a caterer, invite everyone. Make someone's day unforgettable.", 1_500,
       happiness_delta=5, deltas={"conscience": +2},
       one_time=False, requires_min_age=16),
    _p("charity_blood_drive", "Organize a blood drive", "charity",
       "Partner with the Red Cross. Save lives with logistics and a few hours.", 200,
       happiness_delta=3, deltas={"conscience": +4, "health": +1},
       one_time=False, requires_min_age=18),

    # =======================================================================
    # ADDITIONAL ITEMS — filling out the catalog to 250+
    # =======================================================================

    # More housing
    _p("home_deck", "Outdoor deck / patio", "housing",
       "Pressure-treated wood, string lights, an outdoor living space.", 8_000,
       happiness_delta=4, family_wealth_delta=5_000,
       requires_min_age=22, requires_no_existing="home_deck"),
    _p("home_fence", "Privacy fence", "housing",
       "Cedar or vinyl, six feet tall. The yard becomes private.", 4_000,
       happiness_delta=2, requires_min_age=22, requires_no_existing="home_fence"),
    _p("home_fireplace", "Fireplace installation", "housing",
       "Gas or wood-burning. The living room gets a soul.", 6_000,
       happiness_delta=4, family_wealth_delta=4_000,
       requires_min_age=25, requires_no_existing="home_fireplace"),
    _p("home_art_collection", "Art collection for the walls", "housing",
       "Gallery-quality pieces throughout the house. Visitors notice.", 10_000,
       happiness_delta=4, deltas={"artistic": +2, "appearance": +1},
       family_wealth_delta=6_000, requires_min_age=25),
    _p("home_closet_system", "Custom closet system", "housing",
       "Built-in organizers, lighting, shoe racks. Everything has its place.", 3_000,
       happiness_delta=2, deltas={"appearance": +1},
       requires_min_age=22, requires_no_existing="home_closet_system"),
    _p("home_appliance_upgrade", "Appliance upgrade package", "housing",
       "New washer, dryer, dishwasher, refrigerator. All stainless, all quiet.", 5_000,
       happiness_delta=3, requires_min_age=22, one_time=False),

    # More vehicles
    _p("car_convertible", "Convertible", "vehicles",
       "Top down, wind in your hair, and the kind of drive that makes errands feel like adventures.", 42_000,
       happiness_delta=8, deltas={"appearance": +2},
       requires_min_age=22),
    _p("car_minivan", "Minivan", "vehicles",
       "Sliding doors, captain's chairs, room for the whole family and their stuff.", 35_000,
       happiness_delta=3, requires_min_age=25),
    _p("kayak", "Kayak", "vehicles",
       "River mornings, lake weekends, and a workout that doesn't feel like one.", 800,
       happiness_delta=3, deltas={"endurance": +1, "health": +1},
       requires_min_age=14),
    _p("paddleboard", "Paddleboard", "vehicles",
       "Stand-up paddleboarding. Core workout with a view.", 500,
       happiness_delta=2, deltas={"endurance": +1},
       requires_min_age=14),
    _p("snowmobile", "Snowmobile", "vehicles",
       "Winter's version of fun. Fast, loud, and cold.", 10_000,
       happiness_delta=5, deltas={"endurance": +1},
       requires_min_age=18),

    # More lifestyle
    _p("escape_room", "Escape room experience", "lifestyle",
       "Locked in a room with puzzles. Brain games with friends.", 80,
       happiness_delta=3, deltas={"intelligence": +1},
       one_time=False, requires_min_age=12),
    _p("hot_air_balloon", "Hot air balloon ride", "lifestyle",
       "Drifting above the landscape at sunrise. Slow, silent, and surreal.", 300,
       happiness_delta=5, deltas={"wisdom": +1},
       one_time=False, requires_min_age=14),
    _p("pottery_class", "Pottery class", "lifestyle",
       "Hands in clay, a wheel spinning. Something meditative about making a bowl.", 300,
       happiness_delta=3, deltas={"artistic": +2},
       one_time=False, requires_min_age=14),
    _p("wine_collection", "Build a wine collection", "lifestyle",
       "Curated bottles, proper storage. An investment that improves with patience.", 5_000,
       happiness_delta=4, family_wealth_delta=3_000, deltas={"wisdom": +1},
       requires_min_age=25),
    _p("garden_tools", "Premium garden tools", "lifestyle",
       "Japanese steel pruners, copper watering can, ergonomic everything.", 400,
       happiness_delta=2, deltas={"health": +1},
       requires_min_age=20),
    _p("board_game_collection", "Board game collection", "lifestyle",
       "Shelves of strategy, party, and cooperative games. Game nights become a thing.", 300,
       happiness_delta=3, deltas={"intelligence": +1},
       requires_min_age=10),
    _p("painting_supplies", "Art / painting supplies", "lifestyle",
       "Easel, quality brushes, professional-grade paints. The tools to create.", 400,
       happiness_delta=3, deltas={"artistic": +3},
       requires_min_age=12),
    _p("fishing_gear", "Fishing gear", "lifestyle",
       "Rod, reel, tackle box, waders. Early mornings by the water.", 500,
       happiness_delta=3, deltas={"endurance": +1, "wisdom": +1},
       requires_min_age=12),
    _p("camping_gear", "Camping gear", "lifestyle",
       "Tent, sleeping bag, camp stove, headlamp. Everything you need to sleep under the stars.", 600,
       happiness_delta=4, deltas={"endurance": +2},
       requires_min_age=14, requires_no_existing="camping_gear"),
    _p("ski_gear", "Ski / snowboard gear", "lifestyle",
       "Skis or board, boots, helmet, goggles. No more rentals.", 1_200,
       happiness_delta=4, deltas={"endurance": +2, "strength": +1},
       requires_min_age=14, requires_no_existing="ski_gear"),
    _p("golf_set", "Golf club set", "lifestyle",
       "Full set, bag, shoes, and enough balls to lose in every water hazard.", 1_500,
       happiness_delta=3, deltas={"endurance": +1},
       requires_min_age=18, requires_no_existing="golf_set"),
    _p("tennis_gear", "Tennis gear & court time", "lifestyle",
       "Racket, shoes, and a season of weekly court reservations.", 500,
       happiness_delta=3, deltas={"endurance": +2, "strength": +1},
       one_time=False, requires_min_age=14),
    _p("horse_riding_lessons", "Horse riding lessons", "lifestyle",
       "Weekly lessons at a stable. Posture, control, and a connection with a massive animal.", 2_000,
       happiness_delta=5, deltas={"endurance": +1, "strength": +1, "wisdom": +1},
       one_time=False, requires_min_age=10),
    _p("sailing_lessons", "Sailing lessons", "lifestyle",
       "Learn to read the wind, trim the sails, and navigate by feel.", 1_500,
       happiness_delta=4, deltas={"endurance": +1, "wisdom": +2},
       one_time=False, requires_min_age=14),
    _p("haunted_house", "Haunted house experience", "lifestyle",
       "Professional scare actors, elaborate sets. Fun if you're into that sort of thing.", 50,
       happiness_delta=2, one_time=False, requires_min_age=14),
    _p("trampoline_park", "Trampoline park visit", "lifestyle",
       "Bouncing, flipping, foam pits. Kid energy in adult bodies.", 40,
       happiness_delta=2, deltas={"endurance": +1},
       one_time=False, requires_min_age=10),
    _p("zoo_membership", "Zoo / aquarium membership", "lifestyle",
       "Unlimited visits, member events, and a behind-the-scenes tour.", 200,
       happiness_delta=3, deltas={"wisdom": +1},
       requires_min_age=10, one_time=False),
    _p("museum_membership", "Museum membership", "lifestyle",
       "Free admission, special exhibitions, and invites to opening nights.", 150,
       happiness_delta=2, deltas={"intelligence": +1, "artistic": +1},
       requires_min_age=12, one_time=False),
    _p("botanical_garden", "Botanical garden membership", "lifestyle",
       "Seasonal walks through curated gardens. Peace and greenery.", 100,
       happiness_delta=2, deltas={"wisdom": +1},
       requires_min_age=12, one_time=False),

    # More tech
    _p("action_camera", "Action camera", "tech",
       "Waterproof, shockproof, records in 4K. Mount it on anything.", 400,
       happiness_delta=2, deltas={"artistic": +1},
       requires_min_age=14),
    _p("instant_camera", "Instant camera", "tech",
       "Point, shoot, shake. Physical photos in sixty seconds.", 150,
       happiness_delta=2, deltas={"artistic": +1},
       requires_min_age=12),
    _p("turntable", "Record player & vinyl collection", "tech",
       "Warm analog sound and the ritual of dropping a needle.", 500,
       happiness_delta=3, deltas={"artistic": +1, "musical": +1},
       requires_min_age=16),
    _p("portable_speaker", "Premium portable speaker", "tech",
       "Waterproof, loud, and the soundtrack to every outdoor gathering.", 250,
       happiness_delta=2, requires_min_age=14),
    _p("electric_scooter", "Electric scooter", "tech",
       "Last-mile transport. Fold it, charge it, skip traffic.", 600,
       happiness_delta=2, requires_min_age=16),
    _p("home_weather_station", "Home weather station", "tech",
       "Temperature, humidity, wind, rain. Know what's coming before the app does.", 200,
       happiness_delta=1, deltas={"intelligence": +1},
       requires_min_age=14),

    # More health
    _p("boxing_classes", "Boxing classes", "health",
       "Heavy bag, speed bag, footwork. Stress relief with gloves on.", 800,
       happiness_delta=4, deltas={"strength": +3, "endurance": +2},
       one_time=False, requires_min_age=14),
    _p("swim_lessons", "Swimming lessons", "health",
       "Proper stroke technique, endurance laps. The pool becomes a sanctuary.", 400,
       happiness_delta=3, deltas={"endurance": +2, "health": +1},
       one_time=False, requires_min_age=10),
    _p("pilates_sessions", "Pilates sessions", "health",
       "Core strength, flexibility, and posture work. Your back will thank you.", 600,
       happiness_delta=3, deltas={"endurance": +1, "health": +2},
       one_time=False, requires_min_age=16),
    _p("hiking_boots", "Quality hiking boots", "health",
       "Waterproof, ankle support, Gore-Tex lined. Weekend trails become serious.", 250,
       happiness_delta=2, deltas={"endurance": +1},
       requires_min_age=14, requires_no_existing="hiking_boots"),
    _p("running_shoes", "Premium running shoes", "health",
       "Proper fit, carbon plate, a shoe that makes you want to run.", 200,
       happiness_delta=1, deltas={"endurance": +1},
       requires_min_age=14, one_time=False),
    _p("vitamin_supplements", "Quality vitamin supplements", "health",
       "D3, omega-3, magnesium. The basics that most people are deficient in.", 200,
       happiness_delta=1, deltas={"health": +1},
       one_time=False, requires_min_age=18),
    _p("ergonomic_chair", "Ergonomic office chair", "health",
       "Adjustable everything, lumbar support, breathable mesh. Hours at a desk without the ache.", 800,
       happiness_delta=2, deltas={"health": +1},
       requires_min_age=18, requires_no_existing="ergonomic_chair"),

    # More education
    _p("edu_cooking_course", "Cooking course (intensive)", "education",
       "Two weeks of professional culinary instruction. Knife skills, sauces, plating.", 2_000,
       happiness_delta=4, deltas={"artistic": +2, "intelligence": +1},
       one_time=False, requires_min_age=16),
    _p("edu_astronomy", "Astronomy course", "education",
       "Constellations, planetary science, telescope technique. The universe in a semester.", 500,
       happiness_delta=3, deltas={"intelligence": +2, "wisdom": +1},
       one_time=False, requires_min_age=12),
    _p("edu_philosophy", "Philosophy course", "education",
       "Ethics, logic, existentialism. Learn to think about thinking.", 600,
       happiness_delta=2, deltas={"wisdom": +3, "intelligence": +1},
       one_time=False, requires_min_age=16),
    _p("edu_woodworking", "Woodworking class", "education",
       "Joinery, finishing, tool use. Build a table, a shelf, something with your hands.", 800,
       happiness_delta=3, deltas={"artistic": +2, "strength": +1},
       one_time=False, requires_min_age=14),
    _p("edu_gardening", "Master gardener course", "education",
       "Soil science, plant disease, seasonal planning. The garden becomes an ecosystem.", 400,
       happiness_delta=3, deltas={"wisdom": +2, "intelligence": +1},
       one_time=False, requires_min_age=16),

    # More subscriptions
    _p("sub_garden_service", "Garden maintenance service", "subscription",
       "Weekly mowing, seasonal planting, hedge trimming. The yard stays perfect.", 0,
       monthly_cost=150, requires_min_age=22,
       deltas={"happiness": +1}),
    _p("sub_laundry", "Laundry service", "subscription",
       "Pickup, wash, fold, deliver. One fewer chore.", 0,
       monthly_cost=80, requires_min_age=22,
       deltas={"happiness": +1}),
    _p("sub_tutoring", "Tutoring for children", "subscription",
       "Weekly sessions for your kids in math, reading, or whatever they're struggling with.", 0,
       monthly_cost=200, requires_min_age=25,
       deltas={"conscience": +2}),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _scale_for_country(country: Country) -> float:
    """Same scale as careers module — keeps relative affordability sensible."""
    return max(0.05, country.gdp_pc / 50000)


def scaled_cost(purchase: Purchase, country: Country) -> int:
    if purchase.base_cost <= 0:
        return 0
    return max(1, int(purchase.base_cost * _scale_for_country(country)))


def get_purchase(key: str) -> Purchase | None:
    return next((p for p in PURCHASES if p.key == key), None)


def list_purchases(character: Character, country: Country) -> list[dict]:
    """Return every purchase annotated with the character's eligibility,
    affordability (#73), and ownership / subscription state. Used by the
    frontend's spend panel.

    Repeat purchases (vacations, charity, family gifts) are intentionally
    NOT marked as owned (#76) — buying one doesn't lock you out of the
    next. Only ``one_time`` items get the owned tag.
    """
    out = []
    scale = _scale_for_country(country)
    for p in PURCHASES:
        cost = scaled_cost(p, country)
        monthly = int(p.monthly_cost * scale) if p.monthly_cost else 0
        eligible, reason = _check_eligibility(p, character, country)
        # #76: only one-time purchases get the owned flag. Repeats can
        # always be re-bought.
        owned = p.one_time and any(rec.get("key") == p.key for rec in character.purchases)
        subscribed = p.category == "subscription" and p.key in character.subscriptions
        # #73: affordability is a separate gate from eligibility. The
        # listing returns it so the frontend can disable Buy when broke
        # without making a separate call only to get a 400.
        affordable = character.money >= cost
        # If not eligible AND no other reason, mention affordability.
        if eligible and not affordable:
            reason = f"need ${cost:,}, have ${character.money:,}"
        # Pretty-printed effect chips for the UI (#77)
        effects = []
        if p.deltas:
            for k, v in p.deltas.items():
                if v:
                    sign = "+" if v > 0 else ""
                    effects.append(f"{sign}{v} {k}")
        if p.happiness_delta:
            effects.append(f"+{p.happiness_delta} happiness")
        if p.family_wealth_delta:
            effects.append(f"+${int(p.family_wealth_delta * scale):,} family wealth")
        out.append({
            "key": p.key,
            "name": p.name,
            "category": p.category,
            "description": p.description,
            "cost": cost,
            "monthly_cost": monthly,
            "happiness_delta": p.happiness_delta,
            "family_wealth_delta": int(p.family_wealth_delta * scale) if p.family_wealth_delta else 0,
            "one_time": p.one_time,
            "eligible": eligible and affordable,
            "affordable": affordable,
            "reason": reason,
            "owned": owned,
            "subscribed": subscribed,
            "effects": effects,
        })
    return out


def _check_eligibility(p: Purchase, character: Character, country: Country) -> tuple[bool, str | None]:
    if character.age < p.requires_min_age:
        return False, f"requires age {p.requires_min_age}+"
    if p.min_health_services and country.health_services_pct < p.min_health_services:
        return False, f"requires good local healthcare (≥{p.min_health_services}% services)"
    if p.requires_no_existing and any(rec.get("key") == p.requires_no_existing for rec in character.purchases):
        return False, "you already own one"
    if p.category == "subscription" and p.key in character.subscriptions:
        return False, "already subscribed"
    return True, None


@dataclass
class BuyResult:
    success: bool
    message: str
    cost: int = 0


def buy(character: Character, country: Country, purchase_key: str, year: int) -> BuyResult:
    """Apply a purchase to the character. Drains money, applies deltas,
    records the purchase / starts the subscription. Returns BuyResult.

    For one-time bigs (houses, cars), records into character.purchases.
    For subscriptions, adds to character.subscriptions and the yearly
    tick will deduct the recurring cost.
    """
    p = get_purchase(purchase_key)
    if p is None:
        return BuyResult(False, f"unknown purchase {purchase_key!r}")

    eligible, reason = _check_eligibility(p, character, country)
    if not eligible:
        return BuyResult(False, reason or "not eligible")

    cost = scaled_cost(p, country)
    if cost > 0 and character.money < cost:
        return BuyResult(False, f"not enough cash (need ${cost:,}, have ${character.money:,})")

    if cost > 0:
        character.money -= cost

    # Apply attribute deltas immediately for one-time purchases. For
    # subscriptions, the deltas are applied yearly by the yearly tick
    # so we don't double-credit them on the buy day.
    scaled_family_wealth = 0
    if p.category != "subscription":
        if p.deltas:
            character.attributes.adjust(**p.deltas)
        if p.happiness_delta:
            character.attributes.adjust(happiness=p.happiness_delta)
        if p.family_wealth_delta:
            scaled_family_wealth = int(p.family_wealth_delta * _scale_for_country(country))
            character.family_wealth += scaled_family_wealth
        character.purchases.append({
            "key": p.key,
            "name": p.name,
            "category": p.category,
            "year": year,
            "cost": cost,
        })
    else:
        character.subscriptions[p.key] = {
            "name": p.name,
            "monthly_cost": int(p.monthly_cost * _scale_for_country(country)),
            "started_year": year,
            "deltas": dict(p.deltas),
        }

    if p.category == "subscription":
        msg = f"You started a {p.name} subscription."
    elif cost > 0:
        msg = f"You bought a {p.name} for ${cost:,}."
    else:
        msg = f"You acquired a {p.name}."

    # #77: write a timeline entry for one-time purchases with the effect
    # summary, so gifts / charity / vacations don't vanish into a
    # transient toast. Subscriptions get yearly entries via
    # apply_subscription_effects, so we skip them here.
    if p.category != "subscription":
        effect_bits = []
        if p.deltas:
            for k, v in p.deltas.items():
                if not v:
                    continue
                sign = "+" if v > 0 else ""
                effect_bits.append(f"{sign}{v} {k}")
        if p.happiness_delta:
            sign = "+" if p.happiness_delta > 0 else ""
            effect_bits.append(f"{sign}{p.happiness_delta} happiness")
        if scaled_family_wealth:
            effect_bits.append(f"+${scaled_family_wealth:,} family wealth")
        suffix = f" ({', '.join(effect_bits)})" if effect_bits else ""
        if cost > 0:
            character.remember(f"Bought a {p.name} for ${cost:,}{suffix}.")
        else:
            character.remember(f"Acquired a {p.name}{suffix}.")

    return BuyResult(True, msg, cost=cost)


def cancel_subscription(character: Character, key: str) -> BuyResult:
    """Cancel a recurring subscription (#66)."""
    if key not in character.subscriptions:
        return BuyResult(False, f"you don't have a {key} subscription")
    name = character.subscriptions[key].get("name", key)
    del character.subscriptions[key]
    return BuyResult(True, f"You cancelled your {name}.")


def yearly_subscription_cost(character: Character) -> int:
    """Total cash drained by all active subscriptions this year."""
    return sum(int(s.get("monthly_cost", 0)) * 12 for s in character.subscriptions.values())


_SUBSCRIPTION_FLAVOR: dict[str, str] = {
    "sub_gym": "Another year at the gym kept you in shape.",
    "sub_therapy": "Therapy helped you process the year.",
    "sub_premium_health": "Your premium healthcare plan kept the doctors close.",
    "sub_hobby": "Your hobbies and streaming brought small joys.",
    "sub_music": "Music streaming kept the soundtrack going.",
    "sub_news": "Staying informed through quality journalism.",
    "sub_online_courses": "You kept learning through online courses.",
    "sub_cloud_storage": "Your data stayed safe in the cloud.",
    "sub_vpn": "Your VPN kept your browsing private.",
    "sub_meal_kit": "Meal kits made cooking easy and healthy.",
    "sub_wine_club": "Monthly wine selections expanded your palate.",
    "sub_coffee": "Premium coffee made every morning better.",
    "sub_language": "Daily language practice paid off little by little.",
    "sub_cleaning": "A clean home every week — one less thing to worry about.",
    "sub_financial_advisor": "Your financial advisor helped optimize your finances.",
    "sub_fitness_app": "Fitness tracking kept you accountable.",
    "sub_meditation": "Daily meditation brought calm and clarity.",
    "sub_pet_insurance": "Pet insurance meant no worrying about vet bills.",
    "sub_identity_protection": "Identity monitoring kept you safe.",
    "sub_audiobooks": "Audiobooks filled the commute with stories and ideas.",
    "sub_personal_stylist": "A stylist kept your wardrobe sharp.",
    "sub_box_hobby": "Monthly surprise boxes kept creative hobbies alive.",
    "sub_coworking": "Your coworking space kept productivity high.",
    "sub_garden_service": "The garden service kept the yard looking sharp.",
    "sub_laundry": "Laundry service freed up hours every week.",
    "sub_tutoring": "Tutoring helped your children keep up in school.",
}


def apply_subscription_effects(character: Character) -> list[dict]:
    """Apply each active subscription's per-year attribute deltas. Called
    by the yearly tick AFTER the cash deduction. Returns a list of
    summary records the engine can surface in the event log so the
    player sees what their subscription is actually doing (#77).
    """
    out = []
    for key, sub in character.subscriptions.items():
        deltas = sub.get("deltas") or {}
        if deltas:
            character.attributes.adjust(**deltas)
        out.append({
            "key": key,
            "name": sub.get("name", key),
            "summary": _SUBSCRIPTION_FLAVOR.get(key, f"Your {sub.get('name', key)} kept paying off."),
            "deltas": deltas,
        })
    return out
