/**
 * Dual-view toggle — switches between Planning Area and Subzone layers.
 * Positioned as an overlay at the top-right of the map container.
 */

import type { ViewMode } from '../../lib/types';

interface ViewSwitcherProps {
  value: ViewMode;
  onChange: (mode: ViewMode) => void;
}

export function ViewSwitcher({ value, onChange }: ViewSwitcherProps) {
  return (
    <div className="view-switcher" role="radiogroup" aria-label="Map view mode">
      <button
        className={`view-switcher__btn ${value === 'planning' ? 'view-switcher__btn--active' : ''}`}
        onClick={() => onChange('planning')}
        role="radio"
        aria-checked={value === 'planning'}
      >
        Planning Areas
      </button>
      <button
        className={`view-switcher__btn ${value === 'subzone' ? 'view-switcher__btn--active' : ''}`}
        onClick={() => onChange('subzone')}
        role="radio"
        aria-checked={value === 'subzone'}
      >
        Subzones
      </button>
    </div>
  );
}
