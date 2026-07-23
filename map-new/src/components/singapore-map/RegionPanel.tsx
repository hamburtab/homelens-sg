export type DrillLevel = 'free' | 'pa' | 'sz';

interface P {
  satellite: boolean;
  showHeatmap: boolean;
  showLabels: boolean;
  drillLevel: DrillLevel;
  onToggleSatellite: () => void;
  onToggleHeatmap: () => void;
  onToggleLabels: () => void;
  onDrillLevel: (level: DrillLevel) => void;
}

const DRILL_OPTIONS: { level: DrillLevel; icon: string; label: string }[] = [
  { level: 'free', icon: '🌐', label: 'Free' },
  { level: 'pa', icon: '🗺️', label: 'Area' },
  { level: 'sz', icon: '🔍', label: 'Zone' },
];

export function RegionPanel({ satellite, showHeatmap, showLabels, drillLevel, onToggleSatellite, onToggleHeatmap, onToggleLabels, onDrillLevel }: P) {
  return (
    <div className="region-panel">
      <div className="region-panel__body region-panel__body--open">
        <div className="region-panel__section-label">Drill</div>
        <div className="region-panel__drill-row">
          {DRILL_OPTIONS.map(o => (
            <button key={o.level} className={`region-panel__drill-btn${drillLevel === o.level ? ' region-panel__drill-btn--active' : ''}`}
              onClick={() => onDrillLevel(o.level)} title={o.label}>
              {o.icon}
            </button>
          ))}
        </div>
        <div className="region-panel__sep" />
        <label className="region-panel__item">
          <span>🛰️ Satellite</span>
          <label className="region-panel__switch">
            <input type="checkbox" checked={satellite} onChange={onToggleSatellite} />
            <span className="region-panel__switch-slider" />
          </label>
        </label>
        <label className="region-panel__item" onClick={onToggleHeatmap}>
          <span>🔥 Heatmap</span>
          <label className="region-panel__switch">
            <input type="checkbox" checked={showHeatmap} onChange={onToggleHeatmap} />
            <span className="region-panel__switch-slider" />
          </label>
        </label>
        <label className="region-panel__item" onClick={onToggleLabels}>
          <span>🏷️ Labels</span>
          <label className="region-panel__switch">
            <input type="checkbox" checked={showLabels} onChange={onToggleLabels} />
            <span className="region-panel__switch-slider" />
          </label>
        </label>
      </div>
    </div>
  );
}
