import { useEffect, useState, useRef, useCallback } from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';
import type { Feature, FeatureCollection } from 'geojson';
import type { LayerCategory, FocusState } from '../../lib/types';
import { toPointFeatures } from '../../lib/geo-utils';
import bbox from '@turf/bbox';

const CANVAS = L.canvas({ padding: 0.5 });
const TRANSIT_IDS = ['bus_stop', 'railway_station'];
const MIN_ZOOM = 14;
const BASE = import.meta.env.BASE_URL;

interface P { activeIds: Set<string>; categories: LayerCategory[]; onFocus: (s:FocusState)=>void; onSelectFeature: (f:Feature,l:string)=>void; drillPA?: string | null; }

function fname(f: Feature) { return (f.properties?.['name']||f.properties?.['name:en']||'') as string; }

/** In-memory cache: pa → transitType → FeatureCollection */
const paCache = new Map<string, Map<string, FeatureCollection>>();

export function TransitLayer({ activeIds, categories, onFocus, onSelectFeature, drillPA }: P) {
  const map = useMap();
  const [zoom, setZoom] = useState(map.getZoom());
  const [fc, setFc] = useState<FeatureCollection | null>(null);
  const layerRef = useRef<L.GeoJSON | null>(null);
  const loadingRef = useRef<Set<string>>(new Set());

  useEffect(() => { const f = () => setZoom(map.getZoom()); map.on('zoomend', f); return () => { map.off('zoomend', f); }; }, [map]);

  // Load per-PA transit data on demand
  const loadPA = useCallback(async (pa: string) => {
    if (paCache.has(pa)) {
      const cached = paCache.get(pa)!;
      // Merge bus_stop + railway_station
      const features: Feature[] = [];
      for (const tid of TRANSIT_IDS) {
        if (!activeIds.has(tid)) continue; if (cached.has(tid)) features.push(...cached.get(tid)!.features);
      }
      setFc(features.length > 0 ? { type: 'FeatureCollection', features } : null);
      return;
    }
    if (loadingRef.current.has(pa)) return;
    loadingRef.current.add(pa);

    const cachedMap = new Map<string, FeatureCollection>();
    paCache.set(pa, cachedMap);

    const allFeatures: Feature[] = [];
    for (const tid of TRANSIT_IDS) {
      if (!activeIds.has(tid)) continue;
      try {
        const url = `${BASE}geojson/transport/by-pa/${pa}_${tid}.geojson`;
        const r = await fetch(url);
        if (!r.ok) continue;
        const data: FeatureCollection = await r.json();
        cachedMap.set(tid, data);
        allFeatures.push(...data.features);
      } catch { /* file doesn't exist for this PA */ }
    }
    loadingRef.current.delete(pa);
    setFc(allFeatures.length > 0 ? { type: 'FeatureCollection', features: allFeatures } : null);
  }, [activeIds]);

  useEffect(() => {
    if (drillPA) loadPA(drillPA);
    else setFc(null);
  }, [drillPA, loadPA]);

  // Render GeoJSON layer
  useEffect(() => {
    if (layerRef.current) { map.removeLayer(layerRef.current); layerRef.current = null; }
    if (zoom < MIN_ZOOM || !fc || !fc.features.length) return;

    const features: Feature[] = [];
    for (const f of fc.features) {
      const tid = (f.properties?.railway && 'railway_station') || (f.properties?.highway && 'bus_stop') || 'bus_stop';
      const cat = categories.find(c => c.id === tid);
      if (!cat || !activeIds.has(tid)) continue;
      (f as any)._cid = tid; (f as any)._color = cat.color; (f as any)._icon = cat.icon;
      features.push(f);
    }
    if (!features.length) return;

    const gl = L.geoJSON({ type: 'FeatureCollection', features } as FeatureCollection, {
      renderer: CANVAS,
      pointToLayer: (f, ll) => {
        const col = (f as any)._color; const name = fname(f);
        const m = L.circleMarker(ll, { radius: 6, fillColor: col, color: '#fff', weight: 1.5, fillOpacity: 0.85, renderer: CANVAS });
        if (name) m.bindTooltip(name, { direction: 'top', offset: [0, -6], opacity: 0.9 });
        (m as any)._feature = f; (m as any)._cid = (f as any)._cid;
        return m;
      },
    } as any);
    gl.on('click', (e: any) => {
      const f = (e.layer as any)._feature as Feature | undefined;
      if (!f) return;
      try { const b = bbox(f); onFocus({ bounds: [[b[1], b[0]], [b[3], b[2]]], label: fname(f) }); } catch { }
      onSelectFeature(f, '');
    });
    gl.addTo(map);
    layerRef.current = gl;
    return () => { if (layerRef.current) { map.removeLayer(layerRef.current); layerRef.current = null; } };
  }, [fc, activeIds, zoom, map, categories, onFocus, onSelectFeature]);

  return null;
}
