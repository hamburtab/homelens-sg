/** Map a 0–100 evidence score to the product's calm coral-to-teal scale. */
export function scoreToColor(score: number): string {
  const bounded = Math.max(0, Math.min(100, score));
  const hue = 12 + bounded * 1.35;
  return `hsl(${Math.round(hue)}, 55%, 48%)`;
}

export function getPAColor(
  paName: string,
  defaultColor: string,
  scores?: Record<string, number>,
): string {
  const score = scores?.[paName];
  return score !== undefined ? scoreToColor(score) : defaultColor;
}
