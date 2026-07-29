import type { Feature } from 'geojson';

const LABELS: Record<string, string> = {
  name: 'Name',
  'name:en': 'English Name',
  'name:zh': 'Chinese Name',
  'name:ms': 'Malay Name',
  'name:ta': 'Tamil Name',
  'addr:street': 'Street',
  'addr:city': 'City',
  operator: 'Operator',
  network: 'Line',
  opening_hours: 'Opening Hours',
  phone: 'Phone',
  website: 'Website',
};

const MRT_LINES: Record<string, string> = {
  BP: 'Bukit Panjang LRT Line',
  CC: 'Circle Line',
  CE: 'Circle Line',
  CG: 'Changi Airport Branch Line',
  CP: 'Punggol LRT Line',
  CR: 'Cross Island Line',
  DT: 'Downtown Line',
  EW: 'East West Line',
  JE: 'Jurong Region Line',
  JS: 'Jurong Region Line',
  JW: 'Jurong Region Line',
  NE: 'North East Line',
  NS: 'North South Line',
  PE: 'Punggol LRT Line',
  PW: 'Punggol LRT Line',
  SE: 'Sengkang LRT Line',
  SW: 'Sengkang LRT Line',
  TE: 'Thomson-East Coast Line',
};

interface DetailRow {
  label: string;
  value: string;
}

function text(value: unknown) {
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'number') return String(value);
  return '';
}

function buildAddress(properties: Record<string, unknown>) {
  const unit = text(properties['addr:unit']);
  const houseNumber = text(properties['addr:housenumber']);
  const street = text(properties['addr:street']);
  const city = text(properties['addr:city']);
  const firstLine = [unit, houseNumber, street].filter(Boolean).join(' ');
  return [firstLine, city].filter(Boolean).join(', ');
}

function stationType(properties: Record<string, unknown>, categoryLabel: string) {
  if (text(properties.station) === 'light_rail' || text(properties.light_rail) === 'yes') return 'LRT Station';
  if (text(properties.station) === 'monorail' || text(properties.monorail) === 'yes') return 'Monorail Station';
  return categoryLabel || 'MRT Station';
}

function lineNames(properties: Record<string, unknown>) {
  const network = text(properties.network);
  const refs = text(properties.ref).split(';').map((ref) => ref.match(/^[A-Z]+/)?.[0]).filter(Boolean) as string[];
  const inferred = [...new Set(refs.map((prefix) => MRT_LINES[prefix]).filter(Boolean))];
  if (inferred.length) return inferred.join(' / ');
  return network;
}

function compactRailwayRows(properties: Record<string, unknown>, categoryLabel: string): DetailRow[] {
  const rows: DetailRow[] = [
    { label: 'Type', value: stationType(properties, categoryLabel) },
    { label: 'Address', value: buildAddress(properties) },
    { label: 'Line', value: lineNames(properties) },
    { label: 'Station Code', value: text(properties.ref) },
    { label: 'Operator', value: text(properties.operator) },
    { label: 'English Name', value: text(properties['name:en']) || text(properties.name) },
    { label: 'Chinese Name', value: text(properties['name:zh']) },
    { label: 'Malay Name', value: text(properties['name:ms']) },
    { label: 'Tamil Name', value: text(properties['name:ta']) },
  ];
  return rows.filter((row) => row.value);
}

function genericRows(properties: Record<string, unknown>) {
  const usefulKeys = ['name:zh', 'name:en', 'addr:housenumber', 'addr:street', 'addr:city', 'operator', 'network', 'opening_hours', 'phone', 'website'];
  return usefulKeys
    .filter((key) => properties[key] !== undefined)
    .map((key) => ({
      label: LABELS[key] || key,
      value: text(properties[key]) || JSON.stringify(properties[key]),
    }))
    .filter((row) => row.value);
}

export function OsmDetailPanel({ feature, categoryLabel, onClose }: { feature: Feature | null; categoryLabel: string; onClose: () => void }) {
  if (!feature) return null;
  const p = feature.properties ?? {};
  const name = text(p.name) || text(p['name:en']);
  const isRailwayStation = categoryLabel === 'MRT Station' || text(p.railway) === 'station' || text(p.station) === 'subway';
  const rows = isRailwayStation ? compactRailwayRows(p, categoryLabel) : genericRows(p);
  return (
    <div className="osm-detail">
      <div className="osm-detail__header"><h3>{name || categoryLabel}</h3><span className="osm-detail__badge">{categoryLabel}</span><button className="osm-detail__close" onClick={onClose}>✕</button></div>
      <div className="osm-detail__body">
        <div className="osm-detail__table">
          {rows.map((row) => (
            <div className="osm-detail__row" key={row.label}>
              <span className="osm-detail__key">{row.label}</span>
              <span className="osm-detail__val">{row.value}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
