import { useState } from 'react';
import type { LayerGroup } from '../../lib/types';

interface P {
  groups: LayerGroup[];
  active: Set<string>;
  onToggle: (id: string) => void;
  onToggleGroup: (gid: string, sel: boolean) => void;
}

export function LayerPanel({ groups, active, onToggle, onToggleGroup }: P) {
  const [panelOpen, setPanelOpen] = useState(true);
  const [collapsed, setCollapsed] = useState<Set<string>>(
    () => new Set(groups.map((group) => group.id)),
  );

  const toggleGroupOpen = (groupId: string) => setCollapsed((previous) => {
    const next = new Set(previous);
    if (next.has(groupId)) next.delete(groupId);
    else next.add(groupId);
    return next;
  });

  return (
    <div className={`layer-panel ${panelOpen ? '' : 'layer-panel--collapsed'}`}>
      <button
        className="layer-panel__header"
        type="button"
        aria-expanded={panelOpen}
        onClick={() => setPanelOpen((open) => !open)}
      >
        <span>📍 地图图层</span>
        <b>{panelOpen ? '▾' : '▸'}</b>
      </button>
      {panelOpen && (
        <div className="layer-panel__list">
          {groups.map((group) => {
            const activeCount = group.categories.filter((category) => active.has(category.id)).length;
            const allActive = activeCount === group.categories.length;
            const groupOpen = !collapsed.has(group.id);
            return (
              <div key={group.id} className="layer-panel__group">
                <div className="layer-panel__group-header">
                  <button
                    className="layer-panel__fold"
                    type="button"
                    aria-expanded={groupOpen}
                    onClick={() => toggleGroupOpen(group.id)}
                  >
                    {groupOpen ? '▾' : '▸'}
                  </button>
                  <button
                    className="layer-panel__group-label"
                    type="button"
                    onClick={() => toggleGroupOpen(group.id)}
                  >
                    {group.label}
                  </button>
                  <span className="layer-panel__group-count">({activeCount}/{group.categories.length})</span>
                  <button
                    className="layer-panel__group-toggle"
                    type="button"
                    onClick={() => onToggleGroup(group.id, !allActive)}
                  >
                    {allActive ? '取消' : '全选'}
                  </button>
                </div>
                {groupOpen && (
                  <div className="layer-panel__items">
                    {group.categories.map((category) => (
                      <label key={category.id} className="layer-panel__item">
                        <input
                          type="checkbox"
                          checked={active.has(category.id)}
                          onChange={() => onToggle(category.id)}
                        />
                        <span className="layer-panel__swatch" style={{ backgroundColor: category.color }} />
                        <span className="layer-panel__icon">{category.icon}</span>
                        <span className="layer-panel__label">{category.label}</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
