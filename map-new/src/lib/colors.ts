/**
 * Color System for Singapore Map
 *
 * Heatmap: red (dense POIs) → yellow → green (sparse POIs).
 * Subzones inherit their parent Planning Area's hue with subtle variations.
 */

import type { ColorMap } from './types';

// ---- HSL Color Representation ----

interface HSL {
  h: number; // 0–360
  s: number; // 0–100
  l: number; // 0–100
}

// ---- Heatmap Color ----

/** Normalized POI scores: name → 0..1 */
type HeatmapScores = Record<string, number>;

/**
 * Map a normalized score (0=sparse, 1=dense) to an HSL heatmap colour.
 * Green (120°) → Yellow (60°) → Red (0°)
 */
// Explicit RGB tri-stop: Green (#22c55e) → Yellow (#eab308) → Red (#ef4444)
function heatmapColor(score: number): string {
  const stretched = score < 0.5
    ? 0.5 * Math.pow(score / 0.5, 1.8)
    : 0.5 + 0.5 * Math.pow((score - 0.5) / 0.5, 0.5);
  // 3-stop interpolation: green(0) → yellow(0.5) → red(1.0)
  const G = [0x22, 0xc5, 0x5e]; // #22c55e
  const Y = [0xea, 0xb3, 0x08]; // #eab308
  const R = [0xef, 0x44, 0x44]; // #ef4444
  let rgb: number[];
  if (stretched <= 0.5) {
    const t = stretched / 0.5;
    rgb = G.map((g, i) => Math.round(g + (Y[i] - g) * t));
  } else {
    const t = (stretched - 0.5) / 0.5;
    rgb = Y.map((y, i) => Math.round(y + (R[i] - y) * t));
  }
  return `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
}

/**
 * Build a heatmap ColorMap using percentile-based mapping so colours are
 * evenly spread: ~20% green, ~20% yellow-green, ~20% yellow,
 * ~20% orange, ~20% red — regardless of score distribution shape.
 */
export function generateColorMap(ids: string[], scores: HeatmapScores | null): ColorMap {
  const map: ColorMap = new Map();

  if (scores) {
    // Log-scale normalization: density spans 0.1→500+, log maps it to 0→1 sensibly
    const vals = Object.values(scores).filter(v => v > 0);
    const logMin = Math.log10(Math.min(...vals, 0.1));
    const logMax = Math.log10(Math.max(...vals, 1));
    const logRange = logMax - logMin || 1;

    for (const id of ids) {
      const raw = scores[id] ?? 0;
      const logVal = raw > 0 ? Math.log10(raw) : logMin;
      const linear = Math.max(0, Math.min(1, (logVal - logMin) / logRange));
      const norm = Math.pow(linear, 2.2); // stretch low end → more green, less red overall
      map.set(id, heatmapColor(norm));
    }
  } else {
    // Fallback while scores load: green→yellow→red spread
    for (let i = 0; i < ids.length; i++) {
      const pct = ids.length > 1 ? i / (ids.length - 1) : 0.5;
      map.set(ids[i], heatmapColor(pct));
    }
  }
  return map;
}

// ---- HSL String Parsing ----

/** Parse "hsl(H, S%, L%)" back into {h, s, l} */
export function parseHSL(hslStr: string): HSL {
  const match = hslStr.match(/hsl\((\d+),\s*(\d+)%,\s*(\d+)%\)/);
  if (!match) {
    return { h: 0, s: 50, l: 50 };
  }
  return {
    h: Number(match[1]),
    s: Number(match[2]),
    l: Number(match[3]),
  };
}

/** Format {h, s, l} back to "hsl(H, S%, L%)" */
export function formatHSL({ h, s, l }: HSL): string {
  return `hsl(${Math.round(h)}, ${Math.round(s)}%, ${Math.round(l)}%)`;
}

// ---- Subzone Variant Generator ----

/**
 * Deterministic pseudo-random based on a string seed.
 * Same subzone always gets the same variant colour.
 */
function seededRandom(seed: string): number {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) {
    hash = ((hash << 5) - hash + seed.charCodeAt(i)) | 0;
  }
  return (hash >>> 0) / 0xffffffff;
}

/**
 * Generate a subzone variant colour that inherits the parent Planning Area's base hue.
 *
 * Strategy:
 *  - Hue stays within ±8° of the parent
 *  - Saturation varies ±15%
 *  - Lightness varies ±10%
 *
 * @param parentColor - HSL string of the parent Planning Area
 * @param subzoneId - SUBZONE_N used as deterministic seed
 */
export function subzoneColor(parentColor: string, subzoneId: string): string {
  const base = parseHSL(parentColor);
  const rng = seededRandom(subzoneId);

  return formatHSL({
    h: (base.h + (rng - 0.5) * 16 + 360) % 360,
    s: Math.min(100, Math.max(20, base.s + (rng - 0.5) * 30)),
    l: Math.min(85, Math.max(35, base.l + (rng - 0.5) * 20)),
  });
}

// ---- Active / Highlight Colours ----

/** Colour applied to the currently selected polygon */
export const SELECTED_COLOR = '#ef6b4a'; // coral (HomeLens)

/** Border colour for selected polygon */
export const SELECTED_BORDER = '#d4552f'; // coral dark
