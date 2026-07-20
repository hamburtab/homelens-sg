/**
 * Planning Area (Level 1) GeoJSON layer.
 *
 * Renders 55 polygons each filled with its master colour.
 * Handles hover highlight and click-to-select with native Leaflet
 * setStyle calls to avoid React re-render overhead.
 *
 * Uses refs for onSelect/onHover to avoid stale closure bugs —
 * Leaflet event handlers always call the latest prop references.
 */

import { useRef, useEffect, useCallback } from 'react';
import { GeoJSON } from 'react-leaflet';
import type { GeoJSON as LeafletGeoJSON, Layer } from 'leaflet';
import type { Feature } from 'geojson';
import type {
  PlanningAreaCollection,
  SelectedRegion,
  ColorMap,
} from '../../lib/types';
import { SELECTED_COLOR, SELECTED_BORDER } from '../../lib/colors';

interface PlanningAreaLayerProps {
  data: PlanningAreaCollection;
  colorMap: ColorMap;
  selectedArea: SelectedRegion | null;
  onSelect: (region: SelectedRegion) => void;
  onHover: (region: SelectedRegion | null) => void;
}

/** Shared path operations available on polygon layers */
type PathLayer = { setStyle: (s: Record<string, unknown>) => void; bringToFront: () => void };

export function PlanningAreaLayer({
  data,
  colorMap,
  selectedArea,
  onSelect,
  onHover,
}: PlanningAreaLayerProps) {
  const geoRef = useRef<LeafletGeoJSON | null>(null);
  const selectedLayerRef = useRef<Layer | null>(null);

  // Keep latest callback refs so Leaflet event closures are never stale
  const onSelectRef = useRef(onSelect);
  const onHoverRef = useRef(onHover);
  onSelectRef.current = onSelect;
  onHoverRef.current = onHover;

  // ---- Sync selected style when selectedArea changes externally ----
  useEffect(() => {
    const geo = geoRef.current;
    if (!geo) return;

    if (selectedLayerRef.current) {
      geo.resetStyle(selectedLayerRef.current);
      selectedLayerRef.current = null;
    }

    if (selectedArea && selectedArea.type === 'planning') {
      geo.eachLayer((layer: Layer) => {
        const feat = (layer as unknown as { feature?: Feature }).feature;
        if (feat?.properties?.PLN_AREA_N === selectedArea.id) {
          (layer as unknown as PathLayer).setStyle({
            fillColor: SELECTED_COLOR,
            fillOpacity: 0.8,
            weight: 3,
            color: SELECTED_BORDER,
          });
          (layer as unknown as PathLayer).bringToFront();
          selectedLayerRef.current = layer;
        }
      });
    }
  }, [selectedArea]);

  // ---- Default style per feature ----
  const getStyle = useCallback(
    (feature: Feature | undefined) => {
      const id = feature?.properties?.PLN_AREA_N as string | undefined;
      const fillColor = id ? colorMap.get(id) || '#cccccc' : '#cccccc';
      return {
        fillColor,
        fillOpacity: 0.6,
        weight: 1,
        color: '#555555',
        opacity: 0.5,
      };
    },
    [colorMap],
  );

  // ---- Bind mouse events — reads callbacks via refs to avoid stale closures ----
  const onEachFeature = useCallback(
    (_feature: Feature, layer: Layer) => {
      const props = _feature.properties as Record<string, string> | undefined;
      const id = props?.PLN_AREA_N ?? '';
      const name = id;

      const l = layer as unknown as PathLayer;

      layer.on({
        mouseover: () => {
          if (layer === selectedLayerRef.current) return;
          l.setStyle({ weight: 3, fillOpacity: 0.85, color: '#222222' });
          l.bringToFront();
          onHoverRef.current({ id, name, type: 'planning' });
        },
        mouseout: () => {
          if (layer !== selectedLayerRef.current) {
            geoRef.current?.resetStyle(layer);
          }
          onHoverRef.current(null);
        },
        click: () => {
          if (selectedLayerRef.current && selectedLayerRef.current !== layer) {
            geoRef.current?.resetStyle(selectedLayerRef.current);
          }

          selectedLayerRef.current = layer;
          l.setStyle({
            fillColor: SELECTED_COLOR,
            fillOpacity: 0.8,
            weight: 3,
            color: SELECTED_BORDER,
          });
          l.bringToFront();
          onSelectRef.current({ id, name, type: 'planning' });
        },
      });
    },
    [], // Stable callback — reads latest props via refs
  );

  useEffect(() => {
    return () => {
      selectedLayerRef.current = null;
    };
  }, []);

  return (
    <GeoJSON
      ref={geoRef}
      key={`planning-${data.features.length}`}
      data={data}
      style={getStyle}
      onEachFeature={onEachFeature}
    />
  );
}
