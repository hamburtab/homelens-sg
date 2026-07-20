/**
 * MarkerLayer — Two-layer architecture to avoid zoom rebuilds.
 *   - Main layer: always mounted, Canvas circleMarker, no rebuild on zoom.
 *   - Transit layer: only mounted at zoom >= 14.
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
import centroid from '@turf/centroid';

const CANVAS = L.canvas({ padding: 0.5 });
const TRANSIT = new Set(['railway_station','bus_stop']);
const ICON_ZOOM = 14;

interface P { activeIds: Set<string>; categories: LayerCategory[]; onFocus: (s:FocusState)=>void; onSelectFeature: (f:Feature,l:string)=>void; focusGeometry?: Feature<Polygon|MultiPolygon>|null; }

function fname(f: Feature) { return (f.properties?.['name']||f.properties?.['name:en']||'') as string; }

function toPoints(fc: FeatureCollection): FeatureCollection {
  return { type:'FeatureCollection', features: fc.features.map(f => {
    if (f.geometry?.type === 'Point') return f;
    try { const c = centroid(f); return { type:'Feature', properties:f.properties, geometry:c.geometry } as Feature; }
    catch { return f; }
  })};
}

export function MarkerLayer({ activeIds, categories, onFocus, onSelectFeature, focusGeometry }: P) {
  const map = useMap();
  const { load, cacheRef } = useLayerData();
  const [loaded, setLoaded] = useState<Map<string, FeatureCollection>>(new Map());
  const [zoom, setZoom] = useState(map.getZoom());
  const mainRef = useRef<L.GeoJSON | null>(null);
  const transitRef = useRef<L.GeoJSON | null>(null);

  useEffect(() => { const f = () => setZoom(map.getZoom()); map.on('zoomend', f); return () => { map.off('zoomend', f); }; }, [map]);

  const isIn = useCallback((lon:number, lat:number) => {
    if (!focusGeometry) return true;
    try { return booleanPointInPolygon(point([lon,lat]), focusGeometry); } catch { return false; }
  }, [focusGeometry]);

  const getCat = useCallback((id:string) => categories.find(c => c.id===id), [categories]);

  // Load data
  useEffect(() => {
    for (const c of categories.filter(c => activeIds.has(c.id))) {
      if (!loaded.has(c.id)) {
        if (cacheRef.current.has(c.dataSource)) setLoaded(p => new Map(p).set(c.id, cacheRef.current.get(c.dataSource)!));
        else load(c.dataSource).then(d => { if (d) setLoaded(p => new Map(p).set(c.id, d)); });
      }
    }
  }, [activeIds, categories, load, loaded, cacheRef]);

  const handleClick = useCallback((e: any) => {
    const f = (e.layer as any)._feature as Feature|undefined;
    const cid = (e.layer as any)._cid as string|undefined;
    if (!f) return;
    const cat = cid ? getCat(cid) : undefined;
    try { const b = bbox(f); onFocus({ bounds:[[b[1],b[0]],[b[3],b[2]]], label:fname(f)||cat?.label||'' }); } catch {}
    onSelectFeature(f, cat?.label ?? '');
  }, [getCat, onFocus, onSelectFeature]);

  const makeCircle = (f: Feature, ll: L.LatLng, cid: string, color: string, icon: string) => {
    const d = !isIn(ll.lng, ll.lat);
    const col = d ? '#bbb' : color;
    const op = d ? 0.3 : 0.75;
    const showIcons = zoom >= ICON_ZOOM;
    const name = fname(f);

    if (showIcons && name) {
      const label = name.length > 12 ? name.slice(0,10)+'…' : name;
      const html = `<div class="osm-marker" style="--marker-color:${col}"><div class="osm-marker__dot">${icon}</div><div class="osm-marker__label">${label}</div></div>`;
      const ic = L.divIcon({ html, className:'osm-marker-container', iconSize:[68,40], iconAnchor:[34,40] });
      const m = L.marker(ll, { icon:ic });
      (m as any)._feature = f; (m as any)._cid = cid;
      return m;
    }

    const m = L.circleMarker(ll, { radius:5, fillColor:col, color:'transparent', weight:0, fillOpacity:op, renderer:CANVAS });
    if (name) m.bindTooltip(name, { direction:'top', offset:[0,-6], opacity:0.9 });
    (m as any)._feature = f; (m as any)._cid = cid;
    return m;
  };

  // Main layer: non-transit, always mounted, rebuilds on data/focus change (NOT zoom)
  useEffect(() => {
    if (mainRef.current) { map.removeLayer(mainRef.current); mainRef.current = null; }

    const allFeatures: Feature[] = [];
    for (const [cid, data] of loaded) {
      if (!activeIds.has(cid) || TRANSIT.has(cid)) continue;
      const cat = getCat(cid); if (!cat) continue;
      const points = toPoints(data);
      for (const f of points.features) {
        (f as any)._cid = cid; (f as any)._color = cat.color; (f as any)._icon = cat.icon;
        allFeatures.push(f);
      }
    }

    const gl = L.geoJSON({ type:'FeatureCollection', features:allFeatures } as FeatureCollection, {
      renderer: CANVAS,
      pointToLayer: (f, ll) => makeCircle(f, ll, (f as any)._cid, (f as any)._color, (f as any)._icon),
    });
    gl.on('click', handleClick);
    gl.addTo(map);
    mainRef.current = gl;

    return () => { if (mainRef.current) { map.removeLayer(mainRef.current); mainRef.current = null; } };
  }, [loaded, activeIds, map, isIn, getCat, focusGeometry, handleClick]);
  // Note: zoom NOT in deps — main layer doesn't rebuild on zoom.
  // Icons vs circles are decided at render time but require layer rebuild to take effect.
  // Trade-off: accept that icon mode requires data/focus change to refresh.

  // Transit layer: only at zoom >= 14, rebuilds on zoom crossing threshold
  useEffect(() => {
    if (transitRef.current) { map.removeLayer(transitRef.current); transitRef.current = null; }
    if (zoom < ICON_ZOOM) return;

    const allFeatures: Feature[] = [];
    for (const [cid, data] of loaded) {
      if (!activeIds.has(cid) || !TRANSIT.has(cid)) continue;
      const cat = getCat(cid); if (!cat) continue;
      const points = toPoints(data);
      for (const f of points.features) {
        (f as any)._cid = cid; (f as any)._color = cat.color; (f as any)._icon = cat.icon;
        allFeatures.push(f);
      }
    }

    if (allFeatures.length === 0) return;

    const gl = L.geoJSON({ type:'FeatureCollection', features:allFeatures } as FeatureCollection, {
      pointToLayer: (f, ll) => makeCircle(f, ll, (f as any)._cid, (f as any)._color, (f as any)._icon),
    });
    gl.on('click', handleClick);
    gl.addTo(map);
    transitRef.current = gl;

    return () => { if (transitRef.current) { map.removeLayer(transitRef.current); transitRef.current = null; } };
  }, [loaded, activeIds, zoom, map, isIn, getCat, handleClick]);

  return null;
}
