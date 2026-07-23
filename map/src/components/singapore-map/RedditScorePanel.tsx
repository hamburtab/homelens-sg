import { useState } from 'react';
import type { SelectedRegion } from '../../lib/types';

export interface RedditAreaScore {
  scores?: Record<string, number | null>;
}

export interface RedditAreaNlp {
  planning_areas?: Record<string, RedditAreaScore>;
}

interface P {
  data: RedditAreaNlp | null;
  selectedRegion: SelectedRegion | null;
}

const SCORE_LABELS: Array<[string, string]> = [
  ['overall', '综合'],
  ['transport', '交通'],
  ['food', '餐饮'],
  ['noise', '安静程度'],
  ['nature', '自然'],
  ['safety', '安全'],
  ['affordability', '负担能力'],
];

function areaId(region: SelectedRegion | null) {
  if (!region) return '';
  return region.type === 'planning' ? region.id : region.parentId || '';
}

function findAreaScore(data: RedditAreaNlp | null, id: string) {
  const areas = data?.planning_areas;
  if (!areas || !id) return null;
  const direct = areas[id];
  if (direct) return direct;
  const target = id.trim().toLowerCase();
  const matchedKey = Object.keys(areas).find((key) => key.trim().toLowerCase() === target);
  return matchedKey ? areas[matchedKey] : null;
}

function scoreTone(value: number | null | undefined) {
  if (value == null) return 'unknown';
  if (value > 0.5) return 'positive';
  if (value < 0.5) return 'negative';
  return 'neutral';
}

function formatScore(value: number | null | undefined) {
  return value == null ? '-' : value.toFixed(2);
}

export function RedditScorePanel({ data, selectedRegion }: P) {
  const [open, setOpen] = useState(true);
  const id = areaId(selectedRegion);
  const profile = findAreaScore(data, id);

  return (
    <div className={`reddit-score-panel ${open ? '' : 'reddit-score-panel--collapsed'}`}>
      <button
        className="reddit-score-panel__header"
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span><i className="reddit-score-panel__emoji" aria-hidden="true">👩🏻‍💻</i>网友评分</span>
        <b>{open ? '▾' : '▸'}</b>
      </button>
      {open && (
        <div className="reddit-score-panel__body">
          <p>评分基于 Reddit 网友对各规划区的评价提取，高于 0.5 表示整体倾向正向。</p>
          {!id && <div className="reddit-score-panel__empty">点击一个 Planning area 查看评分。</div>}
          {id && !profile && <div className="reddit-score-panel__empty">{id} 暂无网友评分。</div>}
          {profile && (
            <div className="reddit-score-panel__scores">
              {SCORE_LABELS.map(([key, label]) => {
                const value = profile.scores?.[key];
                return (
                  <div className="reddit-score-panel__row" key={key}>
                    <span>{label}</span>
                    <i>
                      <em className={`reddit-score-panel__fill reddit-score-panel__fill--${scoreTone(value)}`} style={{ width: `${Math.max(0, Math.min(1, value ?? 0)) * 100}%` }} />
                    </i>
                    <b>{formatScore(value)}</b>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
