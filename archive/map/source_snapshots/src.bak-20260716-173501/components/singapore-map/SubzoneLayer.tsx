import { useRef, useEffect, useCallback, useState } from 'react';
import { GeoJSON, useMap } from 'react-leaflet';
import type { GeoJSON as LGeo, Layer } from 'leaflet';
import type { Feature } from 'geojson';
import type { SubzoneCollection, SelectedRegion, ColorMap } from '../../lib/types';
import { subzoneColor } from '../../lib/colors';
import { SUBZONE_SCORES, buildScoreTooltip } from '../../lib/subzone-scores';

interface P { data: SubzoneCollection; colorMap: ColorMap; selectedArea: SelectedRegion | null; onSelect: (r: SelectedRegion) => void; onHover: (r: SelectedRegion | null) => void; onFocusSubzone?: (id: string, f: Feature) => void; filterParentId?: string | null; outlineOnly?: boolean; }
type PL = { setStyle(s: Record<string,unknown>): void; bringToFront(): void };

export function SubzoneLayer({ data, colorMap, selectedArea, onSelect, onHover, onFocusSubzone, filterParentId, outlineOnly = false }: P) {
  const geoRef = useRef<LGeo | null>(null);
  const selRef = useRef<Layer | null>(null);
  const map = useMap();
  const [zoom, setZoom] = useState(map.getZoom());
  const osRef = useRef(onSelect); osRef.current = onSelect;
  const ohRef = useRef(onHover); ohRef.current = onHover;
  const ofRef = useRef(onFocusSubzone); ofRef.current = onFocusSubzone;

  useEffect(() => { const f = () => setZoom(map.getZoom()); map.on('zoomend', f); return () => { map.off('zoomend', f); }; }, [map]);

  useEffect(() => {
    const g = geoRef.current; if (!g) return;
    if (selRef.current) { g.resetStyle(selRef.current); selRef.current = null; }
    if (selectedArea?.type === 'subzone') {
      g.eachLayer((l: Layer) => {
        const f = (l as any).feature as Feature|undefined;
        if (f?.properties?.SUBZONE_N === selectedArea.id) {
          (l as unknown as PL).setStyle({ weight:3, color:'#E53935', dashArray:'6 4', fillColor:'transparent', fillOpacity:0 });
          (l as unknown as PL).bringToFront(); selRef.current = l;
        }
      });
    }
  }, [selectedArea]);

  const style = useCallback((f: Feature|undefined) => {
    const p = f?.properties as Record<string,string>|undefined;
    if (outlineOnly) return { fillColor:'transparent', fillOpacity:0, weight:1, color:'#333', opacity:0.5, dashArray:'4 4' };
    const pc = p?.PLN_AREA_N ? (colorMap.get(p.PLN_AREA_N)||'#ccc') : '#ccc';
    const fc = p?.SUBZONE_N ? subzoneColor(pc, p.SUBZONE_N) : pc;
    return { fillColor:fc, fillOpacity:0.25, weight:0.6, color:'#999', opacity:0.3, dashArray:'4 3' };
  }, [colorMap, outlineOnly]);

  const onEach = useCallback((_f: Feature, l: Layer) => {
    const p = _f.properties as Record<string,string>|undefined;
    const id = p?.SUBZONE_N ?? ''; const name = id; const pid = p?.PLN_AREA_N;
    const pl = l as unknown as PL;
    const scores = SUBZONE_SCORES[name];
    const showLabel = Boolean(filterParentId);

    if (name && showLabel) {
      (l as any).bindTooltip(name, { permanent:true, direction:'center', className:'subzone-label-tooltip', opacity:0.85 });
    }
    if (scores) {
      l.on({ mouseover: () => {
        if (l === selRef.current) return;
        pl.setStyle({ weight:3, fillOpacity:0.85, color:'#222', dashArray:'' });
        pl.bringToFront();
        l.unbindTooltip();
        (l as any).bindTooltip(buildScoreTooltip(scores), { direction:'top', sticky:true, className:'subzone-score-tooltip', opacity:0.95, offset:[0,-8] }).openTooltip();
        ohRef.current({ id, name, type:'subzone', parentId:pid });
      }, mouseout: () => {
        if (l !== selRef.current) geoRef.current?.resetStyle(l);
        l.unbindTooltip();
        if (name && showLabel) (l as any).bindTooltip(name, { permanent:true, direction:'center', className:'subzone-label-tooltip', opacity:0.85 });
        ohRef.current(null);
      }, click: () => {
        if (selRef.current && selRef.current !== l) geoRef.current?.resetStyle(selRef.current);
        selRef.current = l;
        pl.setStyle({ weight:3, color:'#E53935', dashArray:'6 4', fillColor:'transparent', fillOpacity:0 });
        pl.bringToFront();
        osRef.current({ id, name, type:'subzone', parentId:pid });
        ofRef.current?.(id, _f);
      }});
    } else {
      l.on({
        mouseover: () => { if (l === selRef.current) return; pl.setStyle({ weight:3, fillOpacity:0.85, color:'#222', dashArray:'' }); pl.bringToFront(); ohRef.current({ id, name, type:'subzone', parentId:pid }); },
        mouseout: () => { if (l !== selRef.current) geoRef.current?.resetStyle(l); ohRef.current(null); },
        click: () => {
          if (selRef.current && selRef.current !== l) geoRef.current?.resetStyle(selRef.current);
          selRef.current = l;
          pl.setStyle({ weight:3, color:'#E53935', dashArray:'6 4', fillColor:'transparent', fillOpacity:0 });
          pl.bringToFront();
          osRef.current({ id, name, type:'subzone', parentId:pid });
          ofRef.current?.(id, _f);
        },
      });
    }
  }, [filterParentId]);

  useEffect(() => () => { selRef.current = null; }, []);

  const fdata = filterParentId ? { ...data, features: data.features.filter(f => f.properties?.PLN_AREA_N === filterParentId) } : data;

  return <GeoJSON ref={geoRef} key={`sz-${fdata.features.length}-${filterParentId||'all'}`} data={fdata} style={style} onEachFeature={onEach} />;
}
