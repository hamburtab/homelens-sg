export interface DimensionScore { score: number; count: number; }
export interface SubzoneScores { [dim: string]: DimensionScore; }
export const DIMENSION_META: Record<string, { label: string; icon: string }> = {
  education: { label: '教育', icon: '🎓' }, transport: { label: '交通', icon: '🚇' },
  food: { label: '餐饮', icon: '🍽️' }, shopping: { label: '购物', icon: '🛒' },
  recreation: { label: '休闲', icon: '⚽' }, nature: { label: '自然', icon: '🌳' },
};
export const DIM_ORDER = ['education','transport','food','shopping','recreation','nature'];
export const SUBZONE_SCORES: Record<string, SubzoneScores> = {
  "Clementi Central": { education:{score:4.5,count:16}, transport:{score:4.0,count:5}, food:{score:4.2,count:7}, shopping:{score:3.5,count:8}, recreation:{score:4.2,count:11}, nature:{score:4.3,count:12} },
  "Clementi North": { education:{score:4.5,count:16}, transport:{score:3.9,count:6}, food:{score:4.5,count:8}, shopping:{score:3.8,count:9}, recreation:{score:4.2,count:11}, nature:{score:4.4,count:11} },
  "Clementi West": { education:{score:4.5,count:17}, transport:{score:4.1,count:6}, food:{score:4.6,count:7}, shopping:{score:4.2,count:8}, recreation:{score:4.2,count:11}, nature:{score:4.4,count:12} },
  "Clementi Woods": { education:{score:4.4,count:12}, transport:{score:4.0,count:5}, food:{score:4.6,count:7}, shopping:{score:4.0,count:9}, recreation:{score:4.2,count:10}, nature:{score:4.4,count:11} },
  Faber: { education:{score:4.4,count:17}, transport:{score:4.3,count:7}, food:{score:4.4,count:7}, shopping:{score:4.0,count:10}, recreation:{score:4.1,count:11}, nature:{score:4.3,count:10} },
  Pandan: { education:{score:4.5,count:18}, transport:{score:4.0,count:7}, food:{score:4.4,count:8}, shopping:{score:4.3,count:9}, recreation:{score:4.2,count:11}, nature:{score:4.3,count:7} },
  "Sunset Way": { education:{score:4.4,count:12}, transport:{score:4.0,count:7}, food:{score:4.2,count:6}, shopping:{score:3.5,count:8}, recreation:{score:4.2,count:11}, nature:{score:4.3,count:7} },
  "Toh Tuck": { education:{score:4.5,count:17}, transport:{score:4.0,count:7}, food:{score:4.3,count:8}, shopping:{score:4.1,count:7}, recreation:{score:4.3,count:12}, nature:{score:4.1,count:12} },
  "West Coast": { education:{score:4.7,count:17}, transport:{score:4.2,count:7}, food:{score:4.5,count:7}, shopping:{score:4.1,count:8}, recreation:{score:4.2,count:10}, nature:{score:4.3,count:10} },
};
export function buildScoreTooltip(scores: SubzoneScores): string {
  const rows = DIM_ORDER.map(dim => {
    const m = DIMENSION_META[dim]; const s = scores[dim]; if (!s) return '';
    const pct = Math.round((s.score / 5) * 100);
    return `<div class="score-row"><span class="score-row__icon">${m.icon}</span><span class="score-row__label">${m.label}</span><div class="score-bar"><div class="score-bar__fill" style="width:${pct}%"></div></div><span class="score-row__val">${s.score.toFixed(1)}</span></div>`;
  }).join('');
  return `<div class="score-card">${rows}</div>`;
}
