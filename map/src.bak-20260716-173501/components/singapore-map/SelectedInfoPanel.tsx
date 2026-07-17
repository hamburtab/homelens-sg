/**
 * Floating info panel that displays the currently selected region.
 * Hidden when nothing is selected.
 */

import type { SelectedRegion } from '../../lib/types';

interface SelectedInfoPanelProps {
  region: SelectedRegion | null;
}

export function SelectedInfoPanel({ region }: SelectedInfoPanelProps) {
  if (!region) return null;

  return (
    <div className="info-panel" role="status" aria-live="polite">
      <div className="info-panel__header">
        <span className="info-panel__badge">
          {region.type === 'planning' ? 'Planning Area' : 'Subzone'}
        </span>
      </div>
      <h3 className="info-panel__name">{region.name}</h3>
      {region.parentId && (
        <p className="info-panel__parent">
          Part of <strong>{region.parentId}</strong>
        </p>
      )}
      <p className="info-panel__id">ID: {region.id}</p>
    </div>
  );
}
