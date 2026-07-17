/**
 * Color System for Singapore Map
 *
 * Generates a 55-color master palette in HSL space with hues evenly distributed.
 * Subzones inherit their parent Planning Area's hue with subtle variations.
 */

import type { ColorMap } from './types';

// ---- HSL Color Representation ----

interface HSL {
  h: number; // 0–360
  s: number; // 0–100
  l: number; // 0–100
}

// ---- Master Palette Generator ----

/**
 * Build a 55-color palette with evenly-spaced hues.
 * Adjacent hues are shuffled slightly so neighbouring areas don't share similar colors.
 * Uses a golden-ratio-inspired offset to maximise perceptual distance between neighbours.
 */
function buildMasterPalette(): string[] {
  const count = 55;
  const palette: string[] = [];
  // Golden-angle offset (~137.5°) ensures adjacent indices get visually distant hues
  const goldenAngle = 137.508;

  for (let i = 0; i < count; i++) {
    const hue = (i * goldenAngle) % 360;
    // Vary saturation and lightness slightly so the map looks lively
    const saturation = 55 + (i % 3) * 5; // 55–65
    const lightness = 60 + (i % 4) * 3; // 60–69
    palette.push(`hsl(${Math.round(hue)}, ${saturation}%, ${lightness}%)`);
  }

  return palette;
}

/** Master palette — computed once at module load */
const MASTER_PALETTE: string[] = buildMasterPalette();

// ---- Color Map Factory ----

/**
 * Given a sorted list of Planning Area IDs, produce a stable ColorMap.
 * The sort ensures deterministic assignment regardless of GeoJSON feature order.
 *
 * @param planningAreaIds - Unique PLN_AREA_N values, preferably sorted
 * @returns Map<PLN_AREA_N, HSL color string>
 */
export function generateColorMap(planningAreaIds: string[]): ColorMap {
  const sorted = [...planningAreaIds].sort();
  const map: ColorMap = new Map();
  sorted.forEach((id, i) => {
    map.set(id, MASTER_PALETTE[i % MASTER_PALETTE.length]);
  });
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
export const SELECTED_COLOR = '#8B5CF6'; // Purple-500

/** Border colour for selected polygon */
export const SELECTED_BORDER = '#6D28D9'; // Purple-700

// Re-export palette for external consumers (e.g. Legend)
export { MASTER_PALETTE };
