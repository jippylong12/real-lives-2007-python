/**
 * Inline SVG icon library. All icons are 16x16 viewBox, stroke-based,
 * matching the editorial aesthetic. Used by spending tabs, lifestyle
 * tier badges, and profile action buttons.
 *
 * Usage: ICONS.housing  -> SVG string
 */

const ICONS = {
  // ---- Spending categories ----
  housing: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M2 8.5l6-5.5 6 5.5"/><path d="M3.5 7.5v5.5h3v-3.5h3v3.5h3v-5.5"/></svg>`,

  vehicles: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 10.5h11"/><path d="M3.5 10.5l1-4h7l1 4"/><circle cx="4.5" cy="12" r="1"/><circle cx="11.5" cy="12" r="1"/><path d="M2 10.5v2.5h1.5M14 10.5v2.5h-1.5"/></svg>`,

  lifestyle: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="5.5"/><path d="M8 4v4l3 2"/></svg>`,

  tech: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="12" height="8" rx="1.5"/><path d="M5 14h6M8 11v3"/></svg>`,

  health: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M8 13.5s-5-3.5-5-7a3 3 0 0 1 5-2.2A3 3 0 0 1 13 6.5c0 3.5-5 7-5 7z"/></svg>`,

  subscription: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M3 4.5a5 5 0 0 1 10 0"/><path d="M3 4.5v7a5 5 0 0 0 10 0v-7"/><path d="M6 7.5v3M10 7.5v3"/></svg>`,

  education: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2L1.5 5.5 8 9l6.5-3.5L8 2z"/><path d="M3.5 7v4c0 1 2 2.5 4.5 2.5s4.5-1.5 4.5-2.5V7"/><path d="M14.5 5.5v5"/></svg>`,

  charity: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3c-1.5-2-4.5-2-5.5 0S2 6.5 8 12c6-5.5 6.5-7 5.5-9S9.5 1 8 3z"/></svg>`,

  // ---- Lifestyle tiers ----
  tier_0: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12l4-8 4 8"/><path d="M5.5 9h5"/></svg>`,

  tier_1: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="2"/><path d="M8 3v2M8 11v2M3 8h2M11 8h2"/></svg>`,

  tier_2: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="10" height="7" rx="1"/><path d="M5 6V4.5a3 3 0 0 1 6 0V6"/></svg>`,

  tier_3: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 13h11l-2-4h-7l-2 4z"/><path d="M5.5 9l1-3h3l1 3"/><path d="M7 6l1-3 1 3"/></svg>`,

  tier_4: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2l1.8 3.6L14 6.4l-3 2.9.7 4.1L8 11.5l-3.7 1.9.7-4.1-3-2.9 4.2-.8L8 2z"/></svg>`,

  tier_5: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2l1.8 3.6L14 6.4l-3 2.9.7 4.1L8 11.5l-3.7 1.9.7-4.1-3-2.9 4.2-.8L8 2z"/><circle cx="8" cy="7" r="1.5"/></svg>`,

  tier_6: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M4 10c0-3 1.5-5 4-7 2.5 2 4 4 4 7"/><path d="M4 10c0 2.5 1.8 4 4 4s4-1.5 4-4"/><path d="M6.5 10.5c0 1.2.7 2 1.5 2s1.5-.8 1.5-2"/></svg>`,

  // ---- Profile actions ----
  rename: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M10.5 2.5l3 3L5 14H2v-3l8.5-8.5z"/></svg>`,

  delete: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M3 4.5h10M5.5 4.5V3a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1v1.5"/><path d="M4.5 4.5l.5 9a1 1 0 0 0 1 1h4a1 1 0 0 0 1-1l.5-9"/></svg>`,
};
