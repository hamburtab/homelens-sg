/**
 * Classify transit stations by Planning Area.
 * Adds PLN_AREA_N property to each station feature.
 * Run: node scripts/classify-transit.mjs
 */
import { readFileSync, writeFileSync } from 'fs';
import path from 'path';
import bbox from '@turf/bbox';
import booleanPointInPolygon from '@turf/boolean-point-in-polygon';
import { point } from '@turf/helpers';

const PUBLIC = path.resolve(import.meta.dirname, '../public');

// Load Planning Areas
const paRaw = JSON.parse(readFileSync(path.join(PUBLIC, 'planning-areas.geojson'), 'utf-8'));
const paIndex = paRaw.features.map(f => {
  const name = f.properties?.PLN_AREA_N || 'Unknown';
  let b;
  try { b = bbox(f); } catch { b = [0, 0, 0, 0]; }
  return { name, feature: f, bbox: { minLng: b[0], minLat: b[1], maxLng: b[2], maxLat: b[3] } };
});

function findPA(lng, lat) {
  for (const pa of paIndex) {
    const bb = pa.bbox;
    if (lng < bb.minLng || lng > bb.maxLng || lat < bb.minLat || lat > bb.maxLat) continue;
    try { if (booleanPointInPolygon(point([lng, lat]), pa.feature)) return pa.name; } catch {}
  }
  return null;
}

// Classify transit files
const transitFiles = [
  'geojson/transport/bus_stop.geojson',
  'geojson/transport/railway_station.geojson',
];

let total = 0, matched = 0;

for (const file of transitFiles) {
  const fp = path.join(PUBLIC, file);
  const data = JSON.parse(readFileSync(fp, 'utf-8'));
  if (!data.features) continue;

  for (const f of data.features) {
    total++;
    if (!f.geometry) continue;
    try {
      let coords;
      if (f.geometry.type === 'Point') coords = f.geometry.coordinates;
      else if (f.geometry.type === 'MultiPoint') coords = f.geometry.coordinates[0];
      else continue;
      const [lng, lat] = coords;
      const pa = findPA(lng, lat);
      if (pa) {
        f.properties = f.properties || {};
        f.properties.PLN_AREA_N = pa;
        matched++;
      }
    } catch { continue; }
  }

  writeFileSync(fp, JSON.stringify(data));
  console.log(`Updated: ${file} (${data.features.length} features)`);
}

console.log(`Total: ${total}, Matched: ${matched}`);
