import type { SelectedRegion } from './types';

export interface DisplayComment {
  source: 'reddit' | 'google' | string;
  planning_area: string;
  subzone: string | null;
  text: string;
  evidence_span: string | null;
  aspects: string[];
  sentiment: string | null;
  intensity: number | null;
  comment_id: string;
  permalink: string | null;
  reddit_score: number | null;
  google_category: string | null;
}

function normalise(value?: string | null) {
  return (value || '').trim().toLowerCase();
}

export function parseCommentPool(raw: string) {
  return raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .flatMap((line) => {
      try {
        return [JSON.parse(line) as DisplayComment];
      } catch {
        return [];
      }
    });
}

export function pickRegionComments(comments: DisplayComment[], region: SelectedRegion | null) {
  if (!region) return [];
  const planningArea = normalise(region.type === 'planning' ? region.id : region.parentId);
  const subzone = normalise(region.type === 'subzone' ? region.id : null);
  const source = region.type === 'planning' ? 'reddit' : 'google';
  const matches = comments.filter((comment) => {
    if (comment.source !== source) return false;
    if (normalise(comment.planning_area) !== planningArea) return false;
    if (region.type === 'subzone' && normalise(comment.subzone) !== subzone) return false;
    return true;
  });
  if (!matches.length) return [];

  const targetCount = region.type === 'planning'
    ? Math.min(matches.length, 5)
    : Math.min(matches.length, 3);
  return [...matches]
    .sort(() => Math.random() - 0.5)
    .slice(0, targetCount);
}
