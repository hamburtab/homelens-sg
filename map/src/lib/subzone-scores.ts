import type { SubzoneProfile } from './types';

const TOOLTIP_COUNTS = [
  ['MRT', 'railwayStations'],
  ['Bus', 'busStops'],
  ['Malls', 'malls'],
  ['Food', 'foodCourts'],
  ['Parks', 'parks'],
  ['Schools', 'schools'],
] as const;

export function buildFacilityTooltip(profile: SubzoneProfile): string {
  const counts = profile.facilityCounts;
  if (!counts) return `<div class="score-card"><strong>${profile.name}</strong></div>`;
  const rows = TOOLTIP_COUNTS.map(([label, key]) => {
    const count = counts[key] ?? 0;
    return `<div class="score-row score-row--count"><span class="score-row__label">${label}</span><span class="score-row__val">${count}</span></div>`;
  }).join('');
  return `<div class="score-card"><strong>${profile.name}</strong>${rows}</div>`;
}
