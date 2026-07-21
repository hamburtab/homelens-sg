import { useEffect, useState, useRef } from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';
import type { Feature, FeatureCollection } from 'geojson';
import type { LayerCategory, FocusState } from '../../lib/types';
import { useLayerData } from '../../hooks/useLayerData';
import centroid from '@turf/centroid';
import bbox from '@turf/bbox';

const TRANSIT = new Set(['railway_station','bus_stop']);
const MIN_ZOOM = 14;

interface P { activeIds: Set<string>; categories: LayerCategory[]; onFocus: (s:FocusState)=>void; onSelectFeature: (f:Feature,l:string)=>void; }

function fname(f: Feature) { return (f.properties?.['name']||f.properties?.['name:en']||'') as string; }

export function TransitLayer({ activeIds, categories, onFocus, onSelectFeature }: P) {
  const map = useMap();
  const { load, cacheRef } = useLayerData();
  const [loaded, setLoaded] = useState<Map<string, FeatureCollection>>(new Map());
  const [zoom, setZoom] = useState(map.getZoom());
  const layerRef = useRef<L.GeoJSON | null>(null);

  useEffect(() => { const f = () => setZoom(map.getZoom()); map.on('zoomend', f); return () => { map.off('zoomend', f); }; }, [map]);

  useEffect(() => {
    for (const c of categories.filter(c => activeIds.has(c.id) && TRANSIT.has(c.id))) {
      if (!loaded.has(c.id)) {
        if (cacheRef.current.has(c.dataSource)) setLoaded(p => new Map(p).set(c.id, cacheRef.current.get(c.dataSource)!));
        else load(c.dataSource).then(d => { if (d) setLoaded(p => new Map(p).set(c.id, d)); });
      }
    }
  }, [activeIds, categories, load, loaded, cacheRef]);

  useEffect(() => {
    if (layerRef.current) { map.removeLayer(layerRef.current); layerRef.current = null; }
    if (zoom < MIN_ZOOM) return;

    const features: Feature[] = [];
    for (const [cid, data] of loaded) {
      if (!activeIds.has(cid) || !TRANSIT.has(cid)) continue;
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
      pointToLayer: (f, ll) => {
        const col = (f as any)._color; const icon = (f as any)._icon; const name = fname(f);
        const label = name.length > 14 ? name.slice(0,12)+'…' : name;
        const html = `<div class="osm-marker" style="--marker-color:${col}"><div class="osm-marker__dot">${icon}</div><div class="osm-marker__label">${label}</div></div>`;
        const ic = L.divIcon({ html, className:'osm-marker-container', iconSize:[68,40], iconAnchor:[34,40] });
        const m = L.marker(ll, { icon:ic });
        (m as any)._feature = f; (m as any)._cid = (f as any)._cid;
        return m;
      },
    });
    gl.on('click', (e: any) => {
      const f = (e.layer as any)._feature as Feature|undefined;
      if (!f) return;
      try { const b = bbox(f); onFocus({ bounds:[[b[1],b[0]],[b[3],b[2]]], label:fname(f) }); } catch {}
      onSelectFeature(f, '');
    });
    gl.addTo(map);
    layerRef.current = gl;
    return () => { if (layerRef.current) { map.removeLayer(layerRef.current); layerRef.current = null; } };
  }, [loaded, activeIds, zoom, map, categories, onFocus, onSelectFeature]);

  return null;
}
