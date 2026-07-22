/**
 * Generate Singapore mask: world minus Singapore boundary.
 * Uses actual OSM coastline from sg-boundary.geojson.
 */
import { readFileSync, writeFileSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import turfDifference from '@turf/difference';
import { polygon, featureCollection } from '@turf/helpers';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.resolve(__dirname, '../public');

const sg = JSON.parse(readFileSync(path.join(PUBLIC, 'sg-boundary.geojson'), 'utf-8'));
// World polygon clamped to Web Mercator max lat (±85°)
const world = polygon([[[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]]]);
const mask = turfDifference(featureCollection([world, sg]));

if (mask) {
  writeFileSync(path.join(PUBLIC, 'sg-mask.geojson'), JSON.stringify(mask));
  const kb = (readFileSync(path.join(PUBLIC, 'sg-mask.geojson')).length / 1024).toFixed(1);
  console.log('Mask generated:', kb, 'KB, type:', mask.geometry.type);
} else {
  console.log('turf.difference returned null — falling back to strips');
  // Fallback: 4 strips as before
  const coords = sg.geometry.coordinates[0];
  let minLng = Infinity, maxLng = -Infinity, minLat = Infinity, maxLat = -Infinity;
  for (const [lng, lat] of coords) {
    if (lng < minLng) minLng = lng;
    if (lng > maxLng) maxLng = lng;
    if (lat < minLat) minLat = lat;
    if (lat > maxLat) maxLat = lat;
  }
  minLng -= 0.02; maxLng += 0.02; minLat -= 0.02; maxLat += 0.02;
  const strips = {
    type: 'FeatureCollection',
    features: [
      { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[[-180, maxLat], [180, maxLat], [180, 85], [-180, 85], [-180, maxLat]]] } },
      { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[[-180, -85], [180, -85], [180, minLat], [-180, minLat], [-180, -85]]] } },
      { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[[-180, minLat], [minLng, minLat], [minLng, maxLat], [-180, maxLat], [-180, minLat]]] } },
      { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[[maxLng, minLat], [180, minLat], [180, maxLat], [maxLng, maxLat], [maxLng, minLat]]] } },
    ]
  };
  writeFileSync(path.join(PUBLIC, 'sg-mask.geojson'), JSON.stringify(strips));
  console.log('Fallback: 4 strips');
}
