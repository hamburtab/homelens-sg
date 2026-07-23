/**
 * PA-level heatmap: aggregate subzone scores to planning area level,
 * missing PAs get a neutral score.
 */
import { SUBZONE_SCORES, DIM_ORDER } from './subzone-scores';

// Map subzone name → parent PA (from subzones.geojson properties)
// Hardcoded for Clementi pilot; extend as more data arrives
const SZ_TO_PA: Record<string, string> = {
  "Clementi Central": "Clementi", "Clementi North": "Clementi",
  "Clementi West": "Clementi", "Clementi Woods": "Clementi",
  Faber: "Clementi", Pandan: "Clementi", "Sunset Way": "Clementi",
  "Toh Tuck": "Clementi", "West Coast": "Clementi",
};

/** Average score across all 6 dimensions */
function avgScore(scores: Record<string, { score: number }>): number {
  const vals = DIM_ORDER.map(d => scores[d]?.score).filter(Boolean) as number[];
  return vals.length > 0 ? vals.reduce((a,b) => a+b, 0) / vals.length : 3.0;
}

/** Compute PA-level aggregate score */
function computePAScores(): Record<string, number> {
  const pa: Record<string, number[]> = {};
  for (const [sz, scores] of Object.entries(SUBZONE_SCORES)) {
    const paName = SZ_TO_PA[sz] || sz;
    if (!pa[paName]) pa[paName] = [];
    pa[paName].push(avgScore(scores));
  }
  const result: Record<string, number> = {};
  for (const [name, vals] of Object.entries(pa)) {
    result[name] = vals.reduce((a,b) => a+b, 0) / vals.length;
  }
  return result;
}

/** PA name → aggregate score (1-5), missing PAs = 3.0 */
export const PA_SCORES: Record<string, number> = computePAScores();

/**
 * Map a score (1-5) to an HSL color.
 * High scores → warm (red/orange), low scores → cool (blue/green).
 * Neutral (3.0) → light grey-yellow.
 */
export function scoreToColor(score: number): string {
  // Map 1-5 to hue: 1=blue(220) → 3=yellow(50) → 5=red(0)
  const hue = 220 - ((score - 1) / 4) * 220;
  const saturation = 55;
  const lightness = 55 + (Math.abs(score - 3) * 5); // brighter at extremes
  return `hsl(${Math.round(hue)}, ${saturation}%, ${lightness}%)`;
}

/** Get PA color: heatmap if data exists, else default */
export function getPAColor(paName: string, defaultColor: string): string {
  const score = PA_SCORES[paName];
  return score !== undefined ? scoreToColor(score) : defaultColor;
}
