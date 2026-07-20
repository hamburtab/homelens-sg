import type { Feature } from 'geojson';

const LABELS: Record<string, string> = { name:'名称', 'name:en':'英文名', 'name:zh':'中文名', 'addr:street':'街道', 'addr:city':'城市', operator:'运营商', network:'线路', opening_hours:'营业时间', phone:'电话', website:'网站' };

export function OsmDetailPanel({ feature, categoryLabel, onClose }: { feature: Feature | null; categoryLabel: string; onClose: () => void }) {
  if (!feature) return null;
  const p = feature.properties ?? {};
  const name = (p['name'] || p['name:en'] || '') as string;
  const keys = Object.keys(p).filter(k => !['@id','osm_id','osm_type'].includes(k)).sort((a,b) => a.startsWith('name') ? -1 : b.startsWith('name') ? 1 : a.localeCompare(b));
  return (
    <div className="osm-detail">
      <div className="osm-detail__header"><h3>{name || categoryLabel}</h3><span className="osm-detail__badge">{categoryLabel}</span><button className="osm-detail__close" onClick={onClose}>✕</button></div>
      <div className="osm-detail__body"><table className="osm-detail__table"><tbody>
        {keys.map(k => { const v = p[k]; return (<tr key={k}><td className="osm-detail__key">{LABELS[k]||k}</td><td className="osm-detail__val">{typeof v==='string' ? v : JSON.stringify(v)}</td></tr>); })}
      </tbody></table></div>
    </div>
  );
}
