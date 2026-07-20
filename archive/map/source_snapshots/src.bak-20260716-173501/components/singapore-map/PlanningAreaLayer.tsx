import { useRef, useEffect, useCallback, useState } from 'react';
import { GeoJSON, useMap } from 'react-leaflet';
import type { GeoJSON as LGeo, Layer } from 'leaflet';
import type { Feature } from 'geojson';
import type { PlanningAreaCollection, SelectedRegion, ColorMap } from '../../lib/types';
import { SELECTED_COLOR, SELECTED_BORDER } from '../../lib/colors';
import { getPAColor } from '../../lib/pa-heatmap';

interface P { data: PlanningAreaCollection; colorMap: ColorMap; selectedArea: SelectedRegion | null; onSelect: (r: SelectedRegion) => void; onHover: (r: SelectedRegion | null) => void; }
type PL = { setStyle(s: Record<string,unknown>): void; bringToFront(): void };

export function PlanningAreaLayer({ data, colorMap, selectedArea, onSelect, onHover }: P) {
  const geoRef = useRef<LGeo | null>(null);
  const selRef = useRef<Layer | null>(null);
  const map = useMap();
  const [zoom, setZoom] = useState(map.getZoom());
  const osRef = useRef(onSelect); osRef.current = onSelect;
  const ohRef = useRef(onHover); ohRef.current = onHover;

  useEffect(() => {
    const upd = () => {
      const z = map.getZoom(); setZoom(z);
      const g = geoRef.current; if (!g) return;
      const show = z >= 12; const fs = z <= 12 ? 10 : z <= 14 ? 12 : 15;
      g.eachLayer((l: Layer) => {
        try {
          const t = (l as any).getTooltip?.(); if (!t || !t._container) return;
          show ? (l as any).openTooltip() : (l as any).closeTooltip();
          if (show) t._container.style.fontSize = `${fs}px`;
        } catch {}
      });
    };
    map.on('zoomend', upd);
    const t = setTimeout(upd, 200);
    return () => { map.off('zoomend', upd); clearTimeout(t); };
  }, [map]);

  useEffect(() => {
    const g = geoRef.current; if (!g) return;
    if (selRef.current) { g.resetStyle(selRef.current); selRef.current = null; }
    if (selectedArea?.type === 'planning') {
      g.eachLayer((l: Layer) => {
        if ((l as any).feature?.properties?.PLN_AREA_N === selectedArea.id) {
          (l as unknown as PL).setStyle({ fillColor:SELECTED_COLOR, fillOpacity:0.8, weight:3, color:SELECTED_BORDER });
          (l as unknown as PL).bringToFront(); selRef.current = l;
        }
      });
    }
  }, [selectedArea]);

  const style = useCallback((f: Feature|undefined) => {
    const id = f?.properties?.PLN_AREA_N as string|undefined;
    const defColor = id ? (colorMap.get(id)||'#ccc') : '#ccc';
    const heatColor = id ? getPAColor(id, defColor) : defColor;
    return { fillColor: heatColor, fillOpacity:0.22, weight:1, color:'#aaa', opacity:0.25 };
  }, [colorMap]);

  const onEach = useCallback((_f: Feature, l: Layer) => {
    const p = _f.properties as Record<string,string>|undefined;
    const id = p?.PLN_AREA_N ?? ''; const name = id;
    if (name && map.getZoom() >= 12) {
      (l as any).bindTooltip(name, { permanent:true, direction:'center', className:'pa-label-tooltip', opacity:0.75 });
    }
    const pl = l as unknown as PL;
    l.on({
      mouseover: () => { if (l === selRef.current) return; pl.setStyle({ weight:3, fillOpacity:0.85, color:'#222' }); pl.bringToFront(); ohRef.current({ id, name, type:'planning' }); },
      mouseout: () => { if (l !== selRef.current) geoRef.current?.resetStyle(l); ohRef.current(null); },
      click: () => {
        if (selRef.current && selRef.current !== l) geoRef.current?.resetStyle(selRef.current);
        selRef.current = l;
        pl.setStyle({ fillColor:SELECTED_COLOR, fillOpacity:0.8, weight:3, color:SELECTED_BORDER });
        pl.bringToFront();
        osRef.current({ id, name, type:'planning' });
      },
    });
  }, [map]);

  useEffect(() => () => { selRef.current = null; }, []);

  return <GeoJSON ref={geoRef} key={`pa-${data.features.length}`} data={data} style={style} onEachFeature={onEach} />;
}
