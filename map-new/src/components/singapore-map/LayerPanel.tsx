import { useState } from 'react';
import type { LayerGroup, Lang } from '../../lib/types';

interface P {
  groups: LayerGroup[];
  active: Set<string>;
  onToggle: (id: string) => void;
  onToggleGroup: (gid: string, sel: boolean) => void;
  lang: Lang;
  showLabels: boolean;
  onToggleLabels: () => void;
  onToggleLang: () => void;
}

function labelFor(item: { label: string; labelEn?: string }, lang: Lang): string {
  return lang === 'en' && item.labelEn ? item.labelEn : item.label;
}

export function LayerPanel({ groups, active, onToggle, onToggleGroup, lang, showLabels, onToggleLabels, onToggleLang }: P) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [panelClosed, setPanelClosed] = useState(false);
  const tc = (gid: string) => setCollapsed(p => { const n = new Set(p); n.has(gid)?n.delete(gid):n.add(gid); return n; });

  if (panelClosed) {
    return (
      <div className="layer-panel layer-panel--mini">
        <button className="layer-panel__reopen" onClick={() => setPanelClosed(false)} title="展开图层">☰</button>
      </div>
    );
  }

  return (
    <div className="layer-panel">
      <div className="layer-panel__header">
        <span className="layer-panel__title">{lang === 'cn' ? '📍 地图图层' : '📍 Map Layers'}</span>
        <div className="layer-panel__actions">
          <button className={`layer-panel__label-btn${!showLabels?' layer-panel__label-btn--off':''}`} onClick={onToggleLabels} title={lang==='cn'?'显示/隐藏标签':'Toggle labels'}>🏷️</button>
          <button className="layer-panel__lang-btn" onClick={onToggleLang} title={lang==='cn'?'Switch to English':'切换到中文'}>{lang==='cn'?'EN':'中'}</button>
        </div>
        <button className="layer-panel__close" onClick={() => setPanelClosed(true)} title={lang==='cn'?'折叠面板':'Collapse'}>◀</button>
      </div>
      <div className="layer-panel__list">
        {groups.map(g => {
          const ga = g.categories.filter(c => active.has(c.id)).length;
          const all = ga === g.categories.length;
          return (
            <div key={g.id} className="layer-panel__group">
              <div className="layer-panel__group-header">
                <button className="layer-panel__fold" onClick={() => tc(g.id)}>{collapsed.has(g.id)?'▸':'▾'}</button>
                <span className="layer-panel__group-label" onClick={() => onToggleGroup(g.id, !all)}>{labelFor(g, lang)}</span>
                <span className="layer-panel__group-count">({ga}/{g.categories.length})</span>
                <button className="layer-panel__group-toggle" onClick={() => onToggleGroup(g.id, !all)}>{lang==='cn'?(all?'取消':'全选'):(all?'None':'All')}</button>
              </div>
              {!collapsed.has(g.id) && (
                <div className="layer-panel__items">
                  {g.categories.map(c => (
                    <label key={c.id} className="layer-panel__item">
                      <input type="checkbox" checked={active.has(c.id)} onChange={() => onToggle(c.id)} />
                      <span className="layer-panel__swatch" style={{ backgroundColor: c.color }} />
                      <span className="layer-panel__icon">{c.icon}</span>
                      <span className="layer-panel__label">{labelFor(c, lang)}</span>
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
