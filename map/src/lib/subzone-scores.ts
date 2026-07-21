import type { SubzoneProfile } from './types';

export const DIMENSION_META: Record<string, { label: string }> = {
  education: { label: 'Education' }, transport: { label: 'Transport' },
  food: { label: 'Food' }, shopping: { label: 'Shopping' },
  recreation: { label: 'Recreation' }, nature: { label: 'Nature' },
};
export const DIM_ORDER = ['education','transport','food','shopping','recreation','nature'];
export function buildScoreTooltip(profile: SubzoneProfile): string {
  const rows = DIM_ORDER.map(dim => {
    const m = DIMENSION_META[dim]; const s = profile.dimensions[dim]; if (!s || s.score == null) return '';
    const pct = Math.round(s.score);
    return `<div class="score-row"><span class="score-row__label">${m.label}</span><div class="score-bar"><div class="score-bar__fill" style="width:${pct}%"></div></div><span class="score-row__val">${pct}</span></div>`;
  }).join('');
  return `<div class="score-card"><strong>${profile.name}</strong>${rows}</div>`;
}
