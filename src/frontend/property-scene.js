/**
 * Property scene — pixel-art canvas that evolves as the player
 * acquires possessions. Renders a small scene showing the character's
 * house, vehicle, garden, and accessories.
 *
 * Called from renderGame() after every state update.
 */

const PropertyScene = (() => {
  // Pixel size — each "pixel" is drawn as a PX x PX square on the
  // canvas. The canvas is 400x200 CSS pixels (retina-ready at 2x).
  const PX = 4;
  const W = 100;  // grid width in "pixels"
  const H = 50;   // grid height in "pixels"

  // Palette — warm, muted, editorial. Matches the CSS vars.
  const C = {
    sky:          "#d4dce8",
    sky_warm:     "#e8d4c4",
    sky_gold:     "#e8d8a8",
    sky_night:    "#3a3a50",
    cloud:        "#e8ecf2",
    sun:          "#e8c870",
    ground:       "#b8a880",
    grass:        "#7a9860",
    grass_dark:   "#5a7840",
    path:         "#c8b898",
    // Houses
    wall_basic:   "#c8b8a0",
    wall_nice:    "#b8a888",
    wall_luxury:  "#a89878",
    wall_mansion: "#988868",
    roof_basic:   "#8b5e3c",
    roof_nice:    "#7a4e30",
    roof_luxury:  "#5e3a20",
    roof_mansion: "#4a2e18",
    door:         "#5e3a20",
    door_nice:    "#4a2a15",
    window:       "#a8c8e0",
    window_lit:   "#e8d870",
    chimney:      "#888078",
    // Vehicles
    car_basic:    "#7888a0",
    car_nice:     "#506080",
    car_sport:    "#a04030",
    car_luxury:   "#2a2a30",
    wheel:        "#2a2a2a",
    // Nature
    tree_trunk:   "#6a4a2a",
    tree_leaf:    "#5a8840",
    tree_leaf_d:  "#4a7030",
    flower_r:     "#c85050",
    flower_y:     "#d8c040",
    flower_p:     "#8858a0",
    water:        "#6898c0",
    water_light:  "#88b8d8",
    fence:        "#c8b898",
    // Accessories
    solar:        "#4060a0",
    solar_frame:  "#606060",
    dish:         "#a0a0a0",
    mailbox:      "#a04030",
    mailbox_post: "#6a4a2a",
    deck_wood:    "#a08060",
    smoke:        "#b0b0b0",
  };

  function render(canvas, character) {
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const purchases = character.purchases || [];
    const subs = character.subscriptions || {};
    const tier = character.lifestyle_tier ?? 3;
    const owned = new Set(purchases.map(p => p.key));
    const hasSub = (k) => k in subs;

    // Determine best house tier
    const houseTier = _houseTier(owned);
    const carTier = _carTier(owned);

    // Clear
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Sky
    _drawSky(ctx, tier);

    // Ground
    _fillRect(ctx, 0, 35, W, 15, C.grass);
    _fillRect(ctx, 0, 38, W, 12, C.grass_dark);

    // Path to house
    if (houseTier >= 0) {
      _fillRect(ctx, 30, 38, 6, 12, C.path);
      _fillRect(ctx, 0, 42, 36, 3, C.path);
    }

    // Fence
    if (owned.has("home_fence")) {
      for (let x = 2; x < 98; x += 4) {
        if (x >= 28 && x <= 38) continue; // gap for path
        _fillRect(ctx, x, 35, 1, 4, C.fence);
        _fillRect(ctx, x - 1, 35, 3, 1, C.fence);
      }
    }

    // Garden / trees
    if (owned.has("home_garden")) {
      _drawTree(ctx, 8, 30, 1);
      _drawTree(ctx, 16, 32, 0);
      // flowers
      _fillRect(ctx, 10, 36, 1, 1, C.flower_r);
      _fillRect(ctx, 12, 37, 1, 1, C.flower_y);
      _fillRect(ctx, 14, 36, 1, 1, C.flower_p);
      _fillRect(ctx, 20, 37, 1, 1, C.flower_r);
    } else {
      // Default single tree
      _drawTree(ctx, 12, 31, 0);
    }

    // Right side trees
    _drawTree(ctx, 85, 31, 1);
    if (tier >= 4) _drawTree(ctx, 92, 33, 0);

    // Pool
    if (owned.has("home_pool")) {
      _fillRect(ctx, 68, 38, 14, 7, C.water);
      _fillRect(ctx, 69, 39, 12, 5, C.water_light);
      // pool edge
      _fillRect(ctx, 67, 37, 16, 1, C.path);
      _fillRect(ctx, 67, 45, 16, 1, C.path);
    }

    // Deck
    if (owned.has("home_deck")) {
      _fillRect(ctx, 55, 36, 10, 6, C.deck_wood);
      for (let y = 36; y < 42; y += 2) {
        _fillRect(ctx, 55, y, 10, 1, C.wall_basic);
      }
    }

    // House
    if (houseTier >= 0) {
      _drawHouse(ctx, houseTier, owned);
    }

    // Solar panels
    if (owned.has("home_solar") && houseTier >= 1) {
      const roofY = houseTier >= 3 ? 16 : houseTier >= 2 ? 20 : 24;
      for (let i = 0; i < 3; i++) {
        _fillRect(ctx, 38 + i * 4, roofY + 1, 3, 2, C.solar);
        _fillRect(ctx, 38 + i * 4, roofY, 3, 1, C.solar_frame);
      }
    }

    // Satellite dish (smart home)
    if (owned.has("home_smart")) {
      const roofX = houseTier >= 3 ? 52 : 48;
      const roofY = houseTier >= 3 ? 16 : houseTier >= 2 ? 20 : 24;
      _fillRect(ctx, roofX, roofY - 2, 1, 3, C.dish);
      _fillRect(ctx, roofX - 1, roofY - 3, 3, 1, C.dish);
    }

    // Car
    if (carTier >= 0) {
      _drawCar(ctx, carTier);
    }

    // Mailbox
    if (houseTier >= 0) {
      _fillRect(ctx, 22, 37, 2, 1, C.mailbox);
      _fillRect(ctx, 22, 38, 1, 3, C.mailbox_post);
    }

    // Chimney smoke (if sauna/fireplace)
    if (owned.has("home_fireplace") || owned.has("home_sauna")) {
      const chimneyX = houseTier >= 3 ? 36 : 34;
      const chimneyY = houseTier >= 3 ? 13 : houseTier >= 2 ? 17 : 22;
      _fillRect(ctx, chimneyX, chimneyY - 3, 1, 1, C.smoke);
      _fillRect(ctx, chimneyX + 1, chimneyY - 5, 1, 1, C.smoke);
      _fillRect(ctx, chimneyX, chimneyY - 7, 1, 1, C.smoke);
    }
  }

  // --- House tiers ---
  function _houseTier(owned) {
    if (owned.has("house_mansion") || owned.has("house_country_estate") || owned.has("house_penthouse")) return 3;
    if (owned.has("house_luxury") || owned.has("house_family")) return 2;
    if (owned.has("house_starter") || owned.has("house_small_apt")) return 1;
    if (owned.has("house_studio")) return 0;
    return -1;
  }

  function _carTier(owned) {
    if (owned.has("car_hypercar") || owned.has("car_supercar") || owned.has("car_luxury")) return 3;
    if (owned.has("car_sports") || owned.has("car_premium") || owned.has("car_suv_luxury")) return 2;
    if (owned.has("car_sport_sedan") || owned.has("car_electric") || owned.has("car_basic") || owned.has("car_pickup")) return 1;
    if (owned.has("car_used") || owned.has("scooter") || owned.has("motorcycle")) return 0;
    return -1;
  }

  // --- Draw helpers ---
  function _fillRect(ctx, x, y, w, h, color) {
    ctx.fillStyle = color;
    ctx.fillRect(x * PX, y * PX, w * PX, h * PX);
  }

  function _drawSky(ctx, tier) {
    let skyColor, cloudColor;
    if (tier <= 1) {
      skyColor = C.sky;
      cloudColor = C.cloud;
    } else if (tier <= 3) {
      skyColor = "#c8d8e8";
      cloudColor = "#dce4f0";
    } else if (tier <= 5) {
      skyColor = C.sky_warm;
      cloudColor = "#f0e0d0";
    } else {
      skyColor = C.sky_gold;
      cloudColor = "#f0e8c8";
    }
    _fillRect(ctx, 0, 0, W, 35, skyColor);
    // Clouds
    _fillRect(ctx, 70, 6, 8, 2, cloudColor);
    _fillRect(ctx, 72, 5, 4, 1, cloudColor);
    _fillRect(ctx, 15, 10, 6, 2, cloudColor);
    _fillRect(ctx, 16, 9, 4, 1, cloudColor);
    // Sun
    if (tier >= 3) {
      _fillRect(ctx, 88, 4, 4, 4, C.sun);
      _fillRect(ctx, 89, 3, 2, 1, C.sun);
      _fillRect(ctx, 89, 8, 2, 1, C.sun);
      _fillRect(ctx, 87, 5, 1, 2, C.sun);
      _fillRect(ctx, 92, 5, 1, 2, C.sun);
    }
  }

  function _drawTree(ctx, x, y, variant) {
    _fillRect(ctx, x, y + 4, 1, 3, C.tree_trunk);
    if (variant === 0) {
      // Round tree
      _fillRect(ctx, x - 2, y, 5, 4, C.tree_leaf);
      _fillRect(ctx, x - 1, y - 1, 3, 1, C.tree_leaf);
      _fillRect(ctx, x - 1, y + 1, 2, 2, C.tree_leaf_d);
    } else {
      // Tall tree
      _fillRect(ctx, x - 1, y, 3, 4, C.tree_leaf);
      _fillRect(ctx, x, y - 2, 1, 2, C.tree_leaf);
      _fillRect(ctx, x - 1, y + 2, 2, 1, C.tree_leaf_d);
    }
  }

  function _drawHouse(ctx, tier, owned) {
    if (tier === 0) {
      // Studio — tiny box
      _fillRect(ctx, 33, 30, 10, 8, C.wall_basic);
      // roof
      _fillRect(ctx, 32, 28, 12, 2, C.roof_basic);
      _fillRect(ctx, 33, 27, 10, 1, C.roof_basic);
      // door
      _fillRect(ctx, 37, 34, 2, 4, C.door);
      // window
      _fillRect(ctx, 34, 31, 2, 2, C.window);
    } else if (tier === 1) {
      // Starter home
      _fillRect(ctx, 30, 28, 16, 10, C.wall_basic);
      // roof
      _fillRect(ctx, 29, 25, 18, 3, C.roof_basic);
      _fillRect(ctx, 30, 24, 16, 1, C.roof_basic);
      // chimney
      _fillRect(ctx, 34, 21, 2, 4, C.chimney);
      // door
      _fillRect(ctx, 36, 33, 3, 5, C.door);
      // windows
      _fillRect(ctx, 31, 29, 3, 3, C.window);
      _fillRect(ctx, 41, 29, 3, 3, C.window);
    } else if (tier === 2) {
      // Family home — two story
      _fillRect(ctx, 28, 22, 22, 16, C.wall_nice);
      // roof
      _fillRect(ctx, 27, 19, 24, 3, C.roof_nice);
      _fillRect(ctx, 28, 18, 22, 1, C.roof_nice);
      // chimney
      _fillRect(ctx, 33, 15, 2, 4, C.chimney);
      // door
      _fillRect(ctx, 37, 33, 3, 5, C.door_nice);
      _fillRect(ctx, 38, 32, 1, 1, C.window_lit); // door window
      // windows — ground floor
      _fillRect(ctx, 30, 30, 3, 3, C.window);
      _fillRect(ctx, 44, 30, 3, 3, C.window);
      // windows — upper floor
      _fillRect(ctx, 30, 23, 3, 3, C.window);
      _fillRect(ctx, 37, 23, 3, 3, C.window);
      _fillRect(ctx, 44, 23, 3, 3, C.window);
      // garage
      _fillRect(ctx, 50, 30, 6, 8, C.wall_basic);
      _fillRect(ctx, 50, 28, 6, 2, C.roof_nice);
      _fillRect(ctx, 51, 32, 4, 6, C.door);
    } else {
      // Mansion / luxury
      _fillRect(ctx, 25, 20, 32, 18, C.wall_luxury);
      // Wings
      _fillRect(ctx, 22, 24, 4, 14, C.wall_mansion);
      _fillRect(ctx, 56, 24, 4, 14, C.wall_mansion);
      // roof — main
      _fillRect(ctx, 24, 16, 34, 4, C.roof_luxury);
      _fillRect(ctx, 25, 15, 32, 1, C.roof_luxury);
      // roof peak
      _fillRect(ctx, 37, 13, 8, 2, C.roof_mansion);
      _fillRect(ctx, 38, 12, 6, 1, C.roof_mansion);
      // chimneys
      _fillRect(ctx, 30, 12, 2, 4, C.chimney);
      _fillRect(ctx, 50, 12, 2, 4, C.chimney);
      // Grand door
      _fillRect(ctx, 38, 31, 5, 7, C.door_nice);
      _fillRect(ctx, 39, 30, 3, 1, C.wall_luxury); // arch
      _fillRect(ctx, 39, 31, 1, 1, C.window_lit);
      _fillRect(ctx, 41, 31, 1, 1, C.window_lit);
      // columns
      _fillRect(ctx, 37, 28, 1, 10, "#d0c8b8");
      _fillRect(ctx, 43, 28, 1, 10, "#d0c8b8");
      // Windows — many
      for (let x of [27, 31, 35, 45, 49, 53]) {
        _fillRect(ctx, x, 22, 2, 3, C.window);
        if (x >= 27 && x <= 53) {
          _fillRect(ctx, x, 30, 2, 3, C.window);
        }
      }
      // wing windows
      _fillRect(ctx, 23, 27, 2, 2, C.window);
      _fillRect(ctx, 57, 27, 2, 2, C.window);
      // Steps
      _fillRect(ctx, 36, 38, 10, 1, C.path);
      _fillRect(ctx, 35, 39, 12, 1, C.path);
    }

    // Home theater indicator — satellite dish on side
    if (owned.has("home_theater")) {
      const x = tier >= 3 ? 56 : 46;
      const y = tier >= 3 ? 22 : 26;
      _fillRect(ctx, x, y, 2, 2, C.dish);
    }
  }

  function _drawCar(ctx, tier) {
    const x = 6;
    const y = 40;
    const colors = [C.car_basic, C.car_nice, C.car_sport, C.car_luxury];
    const cc = colors[tier] || C.car_basic;

    if (tier <= 1) {
      // Compact car
      _fillRect(ctx, x, y, 8, 3, cc);
      _fillRect(ctx, x + 1, y - 1, 5, 1, cc);
      _fillRect(ctx, x + 2, y - 2, 3, 1, cc);
      // windshield
      _fillRect(ctx, x + 4, y - 1, 1, 1, C.window);
      // wheels
      _fillRect(ctx, x + 1, y + 3, 2, 1, C.wheel);
      _fillRect(ctx, x + 5, y + 3, 2, 1, C.wheel);
    } else if (tier === 2) {
      // Sport car — low and wide
      _fillRect(ctx, x, y + 1, 10, 2, cc);
      _fillRect(ctx, x + 2, y, 6, 1, cc);
      _fillRect(ctx, x + 3, y - 1, 4, 1, cc);
      // windshield
      _fillRect(ctx, x + 5, y - 1, 2, 1, C.window);
      // wheels
      _fillRect(ctx, x + 1, y + 3, 2, 1, C.wheel);
      _fillRect(ctx, x + 7, y + 3, 2, 1, C.wheel);
      // tail light
      _fillRect(ctx, x, y + 1, 1, 1, C.flower_r);
    } else {
      // Luxury / supercar — sleek
      _fillRect(ctx, x, y + 1, 12, 2, cc);
      _fillRect(ctx, x + 2, y, 8, 1, cc);
      _fillRect(ctx, x + 4, y - 1, 4, 1, cc);
      // windshield
      _fillRect(ctx, x + 6, y - 1, 2, 1, C.window);
      _fillRect(ctx, x + 3, y, 2, 1, C.window);
      // wheels
      _fillRect(ctx, x + 1, y + 3, 2, 1, C.wheel);
      _fillRect(ctx, x + 9, y + 3, 2, 1, C.wheel);
      // headlight
      _fillRect(ctx, x + 11, y + 1, 1, 1, C.window_lit);
      // tail light
      _fillRect(ctx, x, y + 1, 1, 1, C.flower_r);
    }
  }

  // --- Dot matrix: purchase density indicator ---
  // Small grid at the bottom of the scene showing owned items as
  // colored dots. Each category has a color; more dots = more stuff.
  function _drawDotMatrix(ctx, character) {
    const purchases = character.purchases || [];
    const subs = character.subscriptions || {};

    const catColors = {
      housing:      "#8b7355",
      vehicles:     "#506080",
      lifestyle:    "#7a6898",
      tech:         "#4a7090",
      health:       "#5a8850",
      subscription: "#887040",
      education:    "#6a5a88",
      charity:      "#a06048",
    };

    // Collect dots: one per purchase + one per subscription
    const dots = [];
    for (const p of purchases) {
      dots.push(catColors[p.category] || "#888");
    }
    for (const key of Object.keys(subs)) {
      dots.push(catColors.subscription);
    }

    if (dots.length === 0) return;

    // Draw dot grid at bottom of canvas
    const startX = 2;
    const startY = 47;
    const cols = 32;
    for (let i = 0; i < Math.min(dots.length, cols * 2); i++) {
      const col = i % cols;
      const row = Math.floor(i / cols);
      _fillRect(ctx, startX + col * 3, startY + row * 2, 2, 1, dots[i]);
    }
  }

  // Public API
  return {
    render(canvas, character) {
      render(canvas, character);
      _drawDotMatrix(canvas.getContext("2d"), character);
    },
  };
})();
