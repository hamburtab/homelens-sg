/**
 * Heatmap preprocessor: counts POIs per Planning Area and outputs scores.
 * Run once: node scripts/heatmap-scores.mjs
 */
import { readFileSync, writeFileSync, readdirSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';
import bbox from '@turf/bbox';
import booleanPointInPolygon from '@turf/boolean-point-in-polygon';
import area from '@turf/area';
import { point } from '@turf/helpers';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.resolve(__dirname, '../public');

// Load Planning Areas
const paRaw = JSON.parse(readFileSync(path.join(PUBLIC, 'planning-areas.geojson'), 'utf-8'));

// Build bbox index for PAs + compute area
const paIndex = paRaw.features.map(f => {
  const geom = f.geometry;
  const name = f.properties?.PLN_AREA_N || 'Unknown';
  let b, areaSqm = 0;
  try { b = bbox(f); areaSqm = area(f); } catch { b = [0, 0, 0, 0]; }
  return { name, feature: f, bbox: { minLng: b[0], minLat: b[1], maxLng: b[2], maxLat: b[3] }, areaSqm };
});

// Get all POI geojson files (excluding planning-areas, subzones, and the mask)
function* walkGeoJSON(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) yield* walkGeoJSON(full);
    else if (entry.name.endsWith('.geojson') && !entry.name.includes('planning') && !entry.name.includes('subzone') && !entry.name.includes('mask') && !entry.name.includes('boundary')) {
      yield full;
    }
  }
}

// Count POIs per PA
const scores = {};
for (const pa of paIndex) scores[pa.name] = 0;

let totalPOIs = 0;
for (const file of walkGeoJSON(path.join(PUBLIC, 'geojson'))) {
  try {
    const data = JSON.parse(readFileSync(file, 'utf-8'));
    if (!data.features) continue;
    for (const f of data.features) {
      if (!f.geometry) continue;
      try {
        // Get point coordinates
        let coords;
        if (f.geometry.type === 'Point') coords = f.geometry.coordinates;
        else if (f.geometry.type === 'MultiPoint') coords = f.geometry.coordinates[0];
        else continue; // skip non-point features
        const [lng, lat] = coords;
        if (lng == null || lat == null) continue;

        // Bbox pre-filter then exact test
        for (const pa of paIndex) {
          const bb = pa.bbox;
          if (lng < bb.minLng || lng > bb.maxLng || lat < bb.minLat || lat > bb.maxLat) continue;
          try {
            const pt = point([lng, lat]);
            if (booleanPointInPolygon(pt, pa.feature)) {
              scores[pa.name]++;
              totalPOIs++;
              break;
            }
          } catch { continue; }
        }
      } catch { continue; }
    }
  } catch { /* skip unreadable files */ }
}

// Also count from public/ top-level POI files (bus_stop data etc.)
for (const fname of readdirSync(PUBLIC)) {
  if (!fname.endsWith('.geojson') || fname.includes('planning') || fname.includes('subzone') || fname.includes('mask') || fname.includes('boundary')) continue;
  try {
    const data = JSON.parse(readFileSync(path.join(PUBLIC, fname), 'utf-8'));
    if (!data.features) continue;
    for (const f of data.features) {
      if (!f.geometry) continue;
      try {
        let coords;
        if (f.geometry.type === 'Point') coords = f.geometry.coordinates;
        else continue;
        const [lng, lat] = coords;
        if (lng == null || lat == null) continue;
        for (const pa of paIndex) {
          const bb = pa.bbox;
          if (lng < bb.minLng || lng > bb.maxLng || lat < bb.minLat || lat > bb.maxLat) continue;
          try {
            if (booleanPointInPolygon(point([lng, lat]), pa.feature)) {
              scores[pa.name] = (scores[pa.name] || 0) + 1;
              totalPOIs++;
              break;
            }
          } catch { continue; }
        }
      } catch { continue; }
    }
  } catch { /* skip */ }
}

// Compute density (POIs per km²)
const densities = {};
for (const pa of paIndex) {
  const count = scores[pa.name] || 0;
  const areaKm2 = pa.areaSqm / 1_000_000; // m² → km²
  densities[pa.name] = areaKm2 > 0 ? count / areaKm2 : 0;
}

const sortedD = Object.entries(densities).sort((a, b) => b[1] - a[1]);
console.log('POI density per km² (top 10):');
for (const [name, d] of sortedD.slice(0, 10)) console.log(`  ${name}: ${d.toFixed(1)}/km²`);
console.log(`Range: ${sortedD[sortedD.length-1]?.[1]?.toFixed(1) ?? 0} - ${sortedD[0]?.[1]?.toFixed(1) ?? 0}`);

writeFileSync(path.join(PUBLIC, 'pa-heatmap.json'), JSON.stringify(densities));
console.log('Saved density scores to public/pa-heatmap.json');
