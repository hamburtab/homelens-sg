/**
 * Optional colour legend showing the Planning Area → colour mapping.
 * Collapsed by default; expands on click.
 */

import { useState } from 'react';
import type { ColorMap } from '../../lib/types';

interface LegendProps {
  colorMap: ColorMap;
}

export function Legend({ colorMap }: LegendProps) {
  const [expanded, setExpanded] = useState(false);

  if (colorMap.size === 0) return null;

  const entries = [...colorMap.entries()];

  return (
    <div className={`legend ${expanded ? 'legend--expanded' : ''}`}>
      <button
        className="legend__toggle"
        onClick={() => setExpanded((prev) => !prev)}
        aria-expanded={expanded}
      >
        {expanded ? 'Hide Legend ▲' : 'Show Legend ▼'}
      </button>
      {expanded && (
        <div className="legend__grid">
          {entries.map(([name, color]) => (
            <div key={name} className="legend__item" title={name}>
              <span
                className="legend__swatch"
                style={{ backgroundColor: color }}
              />
              <span className="legend__label">{name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
