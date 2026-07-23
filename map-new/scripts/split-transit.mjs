/**
 * Split classified transit data by Planning Area.
 * Run: node scripts/split-transit.mjs
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.resolve(__dirname, '../public');
const OUT = path.join(PUBLIC, 'geojson/transport/by-pa');
if (!existsSync(OUT)) mkdirSync(OUT, { recursive: true });

const files = ['bus_stop.geojson', 'railway_station.geojson'];

for (const fname of files) {
  const src = path.join(PUBLIC, 'geojson/transport', fname);
  const data = JSON.parse(readFileSync(src, 'utf-8'));
  const byPA = new Map();

  for (const f of data.features) {
    const pa = f.properties && f.properties.PLN_AREA_N;
    if (!pa) continue;
    let arr = byPA.get(pa);
    if (!arr) { arr = []; byPA.set(pa, arr); }
    arr.push(f);
  }

  const base = fname.replace('.geojson', '');
  let total = 0;
  for (const [pa, features] of byPA) {
    const out = path.join(OUT, `${pa}_${base}.geojson`);
    writeFileSync(out, JSON.stringify({ type: 'FeatureCollection', features }));
    total += features.length;
  }

  console.log(`${fname}: ${data.features.length} features → ${byPA.size} PA files (${total} classified)`);
}

console.log('Done:', OUT);
