/**
 * MarkerLayer — Canvas circleMarkers for non-transit categories.
 * No zoom dependency — always mounted, no rebuild on zoom change.
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

export function MarkerLayer({ activeIds, categories, onFocus, onSelectFeature, focusGeometry }: P) {
  const map = useMap();
  const { load, cacheRef } = useLayerData();
  const [loaded, setLoaded] = useState<Map<string, FeatureCollection>>(new Map());
  const [zoom, setZoom] = useState(map.getZoom());
  const layerRef = useRef<L.GeoJSON | null>(null);

  useEffect(() => { const f = () => setZoom(map.getZoom()); map.on('zoomend', f); return () => { map.off('zoomend', f); }; }, [map]);

  const isIn = useCallback((lon:number, lat:number) => {
    if (!focusGeometry) return true;
    try { return booleanPointInPolygon(point([lon,lat]), focusGeometry); } catch { return false; }
  }, [focusGeometry]);

  useEffect(() => {
    for (const c of categories.filter(c => activeIds.has(c.id) && !TRANSIT.has(c.id))) {
      if (!loaded.has(c.id)) {
        if (cacheRef.current.has(c.dataSource)) setLoaded(p => new Map(p).set(c.id, cacheRef.current.get(c.dataSource)!));
        else load(c.dataSource).then(d => { if (d) setLoaded(p => new Map(p).set(c.id, d)); });
      }
    }
  }, [activeIds, categories, load, loaded, cacheRef]);

  // Rebuild only on data/focus change (NOT zoom — icons accepted as trade-off)
  useEffect(() => {
    if (layerRef.current) { map.removeLayer(layerRef.current); layerRef.current = null; }
    const showIcons = zoom >= ICON_ZOOM;

    const features: Feature[] = [];
    for (const [cid, data] of loaded) {
      if (!activeIds.has(cid) || TRANSIT.has(cid)) continue;
      const cat = categories.find(c => c.id === cid); if (!cat) continue;
      for (const f of data.features) {
        let pf = f;
        if (f.geometry?.type !== 'Point') { try { const c = centroid(f); pf = { type:'Feature', properties:f.properties, geometry:c.geometry } as Feature; } catch {} }
        (pf as any)._cid = cid; (pf as any)._color = cat.color; (pf as any)._icon = cat.icon;
        features.push(pf);
      }
    }
    if (!features.length) return;

    const gl = L.geoJSON({ type:'FeatureCollection', features } as FeatureCollection, {
      renderer: CANVAS,
      pointToLayer: (f, ll) => {
        const cid = (f as any)._cid; const color = (f as any)._color; const icon = (f as any)._icon;
        const d = !isIn(ll.lng, ll.lat); const col = d ? '#bbb' : color; const op = d ? 0.3 : 0.75;
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
      },
    });

    gl.on('click', (e: any) => {
      const f = (e.layer as any)._feature as Feature|undefined;
      if (!f) return;
      const cat = categories.find(c => c.id === (e.layer as any)._cid);
      try { const b = bbox(f); onFocus({ bounds:[[b[1],b[0]],[b[3],b[2]]], label:fname(f)||cat?.label||'' }); } catch {}
      onSelectFeature(f, cat?.label ?? '');
    });

    gl.addTo(map);
    layerRef.current = gl;
    return () => { if (layerRef.current) { map.removeLayer(layerRef.current); layerRef.current = null; } };
  }, [loaded, activeIds, focusGeometry, isIn, map, onSelectFeature, categories, zoom, onFocus]);

  return null;
}
