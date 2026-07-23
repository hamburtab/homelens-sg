/**
 * MarkerLayer — Canvas circleMarkers for non-transit categories.
 * Zoom-aware radius, center-distance icon priority, label toggle.
 */
import { useEffect, useState, useCallback, useRef } from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';
import type { Feature, FeatureCollection } from 'geojson';
import type { Polygon, MultiPolygon } from 'geojson';
import type { LayerCategory, FocusState } from '../../lib/types';
import { useLayerData } from '../../hooks/useLayerData';
import bbox from '@turf/bbox';
import booleanPointInPolygon from '@turf/boolean-point-in-polygon';
import { point } from '@turf/helpers';
import { toPointFeatures } from '../../lib/geo-utils';

const CANVAS = L.canvas({ padding: 0.5 });
const TRANSIT = new Set(['railway_station', 'bus_stop']);
const ICON_ZOOM = 14;
const GLOBAL_MAX_ICONS = 30;

interface P {
  activeIds: Set<string>;
  categories: LayerCategory[];
  onFocus: (s: FocusState) => void;
  onSelectFeature: (f: Feature, l: string) => void;
  focusGeometry?: Feature<Polygon | MultiPolygon> | null;
  showLabels: boolean;
}

function fname(f: Feature) { return (f.properties?.['name'] || f.properties?.['name:en'] || '') as string; }

export function MarkerLayer({ activeIds, categories, onFocus, onSelectFeature, focusGeometry, showLabels }: P) {
  const map = useMap();
  const { load, cacheRef } = useLayerData();
  const [loaded, setLoaded] = useState<Map<string, FeatureCollection>>(new Map());
  const [zoom, setZoom] = useState(map.getZoom());
  const layerRef = useRef<L.GeoJSON | null>(null);

  useEffect(() => {
    const f = () => setZoom(map.getZoom());
    map.on('zoomend', f);
    return () => { map.off('zoomend', f); };
  }, [map]);

  const isIn = useCallback((lon: number, lat: number) => {
    if (!focusGeometry) return true;
    try { return booleanPointInPolygon(point([lon, lat]), focusGeometry); } catch { return false; }
  }, [focusGeometry]);

  useEffect(() => {
    for (const c of categories.filter(c => activeIds.has(c.id) && !TRANSIT.has(c.id))) {
      if (!loaded.has(c.id)) {
        if (cacheRef.current.has(c.dataSource)) setLoaded(p => new Map(p).set(c.id, cacheRef.current.get(c.dataSource)!));
        else load(c.dataSource).then(d => { if (d) setLoaded(p => new Map(p).set(c.id, d)); });
      }
    }
  }, [activeIds, categories, load, loaded, cacheRef]);

  useEffect(() => {
    if (layerRef.current) { map.removeLayer(layerRef.current); layerRef.current = null; }
    const showIcons = map.getZoom() >= ICON_ZOOM;
    // Zoom multiplier: clamp 0.7-1.5 so dots scale with zoom but don't go crazy
    const zm = Math.max(0.7, Math.min(1.5, zoom / ICON_ZOOM));

    const features: Feature[] = [];
    for (const [cid, data] of loaded) {
      if (!activeIds.has(cid) || TRANSIT.has(cid)) continue;
      const cat = categories.find(c => c.id === cid); if (!cat) continue;
      const points = toPointFeatures(data);
      for (const f of points.features) {
        (f as any)._cid = cid; (f as any)._color = cat.color; (f as any)._icon = cat.icon;
        features.push(f);
      }
    }
    if (!features.length) return;

    // Icon priority: sort by center distance, allocate global budget proportionally
    const iconBudget = new Map<string, number>();
    {
      const center = map.getCenter();
      const byCat = new Map<string, Feature[]>();
      for (const f of features) {
        const cid = (f as any)._cid as string;
        if (!byCat.has(cid)) byCat.set(cid, []);
        byCat.get(cid)!.push(f);
      }
      // Proportional budget: each category gets share of GLOBAL_MAX_ICONS
      const totalInside = features.length;
      let allocated = 0;
      for (const [cid, catF] of byCat) {
        const share = Math.max(1, Math.round(GLOBAL_MAX_ICONS * catF.length / totalInside));
        iconBudget.set(cid, share);
        allocated += share;
      }
      // Trim if over budget
      if (allocated > GLOBAL_MAX_ICONS) {
        const sorted = [...iconBudget.entries()].sort((a, b) => b[1] - a[1]);
        for (let i = 0; i < allocated - GLOBAL_MAX_ICONS && i < sorted.length; i++) {
          const cid = sorted[i][0];
          if (iconBudget.get(cid)! > 1) iconBudget.set(cid, iconBudget.get(cid)! - 1);
        }
      }

      const reordered: Feature[] = [];
      for (const [cid, catFeatures] of byCat) {
        const budget = iconBudget.get(cid) ?? 1;
        catFeatures.sort((a, b) => {
          const aC = (a as any).geometry?.type === 'Point' ? (a.geometry as any).coordinates : null;
          const bC = (b as any).geometry?.type === 'Point' ? (b.geometry as any).coordinates : null;
          if (!aC || !bC) return 0;
          const aD = Math.pow(aC[0] - center.lng, 2) + Math.pow(aC[1] - center.lat, 2);
          const bD = Math.pow(bC[0] - center.lng, 2) + Math.pow(bC[1] - center.lat, 2);
          return aD - bD;
        });
        // Picked (closest) features get icon priority, rest become dots — ALL rendered
        const half = Math.ceil(budget / 2);
        const closest = catFeatures.slice(0, half);
        const rest = catFeatures.slice(half);
        for (let i = rest.length - 1; i > 0; i--) {
          const j = Math.floor(Math.random() * (i + 1));
          [rest[i], rest[j]] = [rest[j], rest[i]];
        }
        const picked = closest.concat(rest.slice(0, budget - half));
        const remaining = catFeatures.filter(f => !picked.includes(f));
        reordered.push(...picked, ...remaining);
      }
      features.length = 0;
      Array.prototype.push.apply(features, reordered);
    }

    const gl = L.geoJSON({ type: 'FeatureCollection', features } as FeatureCollection, {
      renderer: CANVAS,
      pointToLayer: (f, ll) => {
        const cid = (f as any)._cid; const color = (f as any)._color; const icon = (f as any)._icon;
        const inside = isIn(ll.lng, ll.lat);
        const hasFocus = !!focusGeometry;

        // Outside focus area: minimal dot — still clickable
        if (!inside) {
          const m = L.circleMarker(ll, { radius: Math.round(2 * zm), fillColor: '#bbb', color: 'transparent', weight: 2, opacity: 0, fillOpacity: 0.35, renderer: CANVAS, interactive: true, bubblingMouseEvents: false });
          m.on('click', () => { onSelectFeature(f, categories.find(c => c.id === cid)?.label ?? ''); });
          return m;
        }

        // Budget exhausted: colored dot — clickable with detail panel
        const budget = iconBudget.get(cid) ?? 0;
        if (budget <= 0) {
          const r = Math.round((hasFocus ? 3 : 4) * zm);
          const op = hasFocus ? 0.55 : 0.75;
          const name = fname(f);
          const m = L.circleMarker(ll, { radius: r, fillColor: color, color: 'transparent', weight: 2, opacity: 0, fillOpacity: op, renderer: CANVAS, interactive: true, bubblingMouseEvents: false });
          (m as any)._feature = f; (m as any)._cid = cid;
          if (name && showLabels) m.bindTooltip(name, { direction: 'top', offset: [0, -6], opacity: 0.85 });
          m.on('click', () => { onSelectFeature(f, categories.find(c => c.id === cid)?.label ?? ''); });
          return m;
        }

        // Full icon rendering (PA focused + zoom ok + budget remaining + showIcons)
        const name = fname(f);
        if (showIcons && name) {
          iconBudget.set(cid, budget - 1);
          const label = name.length > 12 ? name.slice(0, 10) + '…' : name;
          const labelHtml = showLabels ? `<div class="osm-marker__label">${label}</div>` : '';
          const html = `<div class="osm-marker" style="--marker-color:${color}"><div class="osm-marker__dot">${icon}</div>${labelHtml}</div>`;
          const ic = L.divIcon({ html, className: 'osm-marker-container', iconSize: [68, 40], iconAnchor: [34, 40] });
          const m = L.marker(ll, { icon: ic });
          (m as any)._feature = f; (m as any)._cid = cid;
          return m;
        }
        const m = L.circleMarker(ll, { radius: Math.round(5 * zm), fillColor: color, color: 'transparent', weight: 0, fillOpacity: 0.85, renderer: CANVAS });
        if (name && showLabels) m.bindTooltip(name, { direction: 'top', offset: [0, -6], opacity: 0.9 });
        (m as any)._feature = f; (m as any)._cid = cid;
        return m;
      },
    } as any);

    gl.on('click', (e: any) => {
      const f = (e.layer as any)._feature as Feature | undefined;
      if (!f) return;
      const cat = categories.find(c => c.id === (e.layer as any)._cid);
      try { const b = bbox(f); onFocus({ bounds: [[b[1], b[0]], [b[3], b[2]]], label: fname(f) || cat?.label || '' }); } catch { }
      onSelectFeature(f, cat?.label ?? '');
    });

    gl.addTo(map);
    layerRef.current = gl;
    return () => { if (layerRef.current) { map.removeLayer(layerRef.current); layerRef.current = null; } };
  }, [loaded, activeIds, focusGeometry, isIn, map, onSelectFeature, categories, onFocus, zoom, showLabels]);

  return null;
}
