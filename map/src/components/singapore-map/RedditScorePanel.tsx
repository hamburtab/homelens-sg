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
  ['overall', 'Overall'],
  ['transport', 'Transit'],
  ['food', 'Food'],
  ['noise', 'Quietness'],
  ['nature', 'Nature'],
  ['safety', 'Safety'],
  ['affordability', 'Affordability'],
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
        <span><i className="reddit-score-panel__emoji" aria-hidden="true">👩🏻‍💻</i>Reddit Scores</span>
        <b>{open ? '▾' : '▸'}</b>
      </button>
      {open && (
        <div className="reddit-score-panel__body">
          <p>Scores are derived from Reddit comments about each planning area. Values above 0.5 indicate positive sentiment.</p>
          {!id && <div className="reddit-score-panel__empty">Select a planning area to view its scores.</div>}
          {id && !profile && <div className="reddit-score-panel__empty">No Reddit scores are available for {id}.</div>}
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
