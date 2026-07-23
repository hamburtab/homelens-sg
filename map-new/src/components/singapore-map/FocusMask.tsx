import { useMemo } from 'react';
import { GeoJSON } from 'react-leaflet';
import type { Feature, Polygon, MultiPolygon } from 'geojson';
import type { FocusState } from '../../lib/types';
import turfDifference from '@turf/difference';
import { polygon } from '@turf/helpers';

interface P { focus: FocusState | null; focusGeometry?: Feature<Polygon|MultiPolygon> | null; onClear: () => void; }

function worldPoly(): Feature<Polygon> { return polygon([[[-180,-90],[180,-90],[180,90],[-180,90],[-180,-90]]]) as Feature<Polygon>; }

export function FocusMask({ focus, focusGeometry, onClear }: P) {
  const geo = useMemo(() => {
    if (!focus) return null;
    try {
      const w = worldPoly();
      const hole = focusGeometry ?? w;
      return turfDifference({ type:'FeatureCollection', features:[w, hole as Feature<Polygon>] }) as Feature<Polygon|MultiPolygon> | null;
    } catch { return null; }
  }, [focus, focusGeometry]);
  if (!focus || !geo) return null;
  return <GeoJSON key={`mask-${focus.label}`} data={geo} pane="focusMask" style={{ fillColor:'#000', fillOpacity:0.5, color:'transparent', weight:0 }} eventHandlers={{ click: onClear }} interactive />;
}
