import { useState } from 'react';
import type { LayerGroup } from '../../lib/types';

interface P { groups: LayerGroup[]; active: Set<string>; onToggle: (id: string) => void; onToggleGroup: (gid: string, sel: boolean) => void; }

export function LayerPanel({ groups, active, onToggle, onToggleGroup }: P) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const tc = (gid: string) => setCollapsed(p => { const n = new Set(p); n.has(gid)?n.delete(gid):n.add(gid); return n; });
  return (
    <div className="layer-panel">
      <div className="layer-panel__header">📍 地图图层</div>
      <div className="layer-panel__list">
        {groups.map(g => {
          const ga = g.categories.filter(c => active.has(c.id)).length;
          const all = ga === g.categories.length;
          return (
            <div key={g.id} className="layer-panel__group">
              <div className="layer-panel__group-header">
                <button className="layer-panel__fold" onClick={() => tc(g.id)}>{collapsed.has(g.id)?'▸':'▾'}</button>
                <span className="layer-panel__group-label" onClick={() => onToggleGroup(g.id, !all)}>{g.label}</span>
                <span className="layer-panel__group-count">({ga}/{g.categories.length})</span>
                <button className="layer-panel__group-toggle" onClick={() => onToggleGroup(g.id, !all)}>{all?'取消':'全选'}</button>
              </div>
              {!collapsed.has(g.id) && (
                <div className="layer-panel__items">
                  {g.categories.map(c => (
                    <label key={c.id} className="layer-panel__item">
                      <input type="checkbox" checked={active.has(c.id)} onChange={() => onToggle(c.id)} />
                      <span className="layer-panel__swatch" style={{ backgroundColor: c.color }} />
                      <span className="layer-panel__icon">{c.icon}</span>
                      <span className="layer-panel__label">{c.label}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
