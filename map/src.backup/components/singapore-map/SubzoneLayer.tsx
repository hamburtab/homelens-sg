/**
 * Subzone (Level 2) GeoJSON layer.
 *
 * Renders 300+ subzone polygons. Each inherits its parent Planning Area's
 * colour with a deterministic variant, plus dashed inner borders to visually
 * group subzones within the same macro region.
 *
 * Uses refs for onSelect/onHover to avoid stale closure bugs.
 */

import { useRef, useEffect, useCallback } from 'react';
import { GeoJSON } from 'react-leaflet';
import type { GeoJSON as LeafletGeoJSON, Layer } from 'leaflet';
import type { Feature } from 'geojson';
import type {
  SubzoneCollection,
  SelectedRegion,
  ColorMap,
} from '../../lib/types';
import {
  subzoneColor,
  SELECTED_COLOR,
  SELECTED_BORDER,
} from '../../lib/colors';

interface SubzoneLayerProps {
  data: SubzoneCollection;
  colorMap: ColorMap;
  selectedArea: SelectedRegion | null;
  onSelect: (region: SelectedRegion) => void;
  onHover: (region: SelectedRegion | null) => void;
}

type PathLayer = { setStyle: (s: Record<string, unknown>) => void; bringToFront: () => void };

export function SubzoneLayer({
  data,
  colorMap,
  selectedArea,
  onSelect,
  onHover,
}: SubzoneLayerProps) {
  const geoRef = useRef<LeafletGeoJSON | null>(null);
  const selectedLayerRef = useRef<Layer | null>(null);

  // Keep latest callback refs so Leaflet event closures are never stale
  const onSelectRef = useRef(onSelect);
  const onHoverRef = useRef(onHover);
  onSelectRef.current = onSelect;
  onHoverRef.current = onHover;

  // ---- Sync selected style ----
  useEffect(() => {
    const geo = geoRef.current;
    if (!geo) return;

    if (selectedLayerRef.current) {
      geo.resetStyle(selectedLayerRef.current);
      selectedLayerRef.current = null;
    }

    if (selectedArea && selectedArea.type === 'subzone') {
      geo.eachLayer((layer: Layer) => {
        const feat = (layer as unknown as { feature?: Feature }).feature;
        if (feat?.properties?.SUBZONE_N === selectedArea.id) {
          (layer as unknown as PathLayer).setStyle({
            fillColor: SELECTED_COLOR,
            fillOpacity: 0.8,
            weight: 3,
            color: SELECTED_BORDER,
            dashArray: '',
          });
          (layer as unknown as PathLayer).bringToFront();
          selectedLayerRef.current = layer;
        }
      });
    }
  }, [selectedArea]);

  // ---- Default style: parent colour variant + dashed border ----
  const getStyle = useCallback(
    (feature: Feature | undefined) => {
      const props = feature?.properties as Record<string, string> | undefined;
      const parentId = props?.PLN_AREA_N;
      const subzoneId = props?.SUBZONE_N;

      const parentColor = parentId
        ? colorMap.get(parentId) || '#cccccc'
        : '#cccccc';
      const fillColor = subzoneId
        ? subzoneColor(parentColor, subzoneId)
        : parentColor;

      return {
        fillColor,
        fillOpacity: 0.5,
        weight: 0.8,
        color: '#666666',
        opacity: 0.5,
        dashArray: '4 3',
      };
    },
    [colorMap],
  );

  // ---- Mouse events — reads callbacks via refs to avoid stale closures ----
  const onEachFeature = useCallback(
    (_feature: Feature, layer: Layer) => {
      const props = _feature.properties as Record<string, string> | undefined;
      const id = props?.SUBZONE_N ?? '';
      const name = id;
      const parentId = props?.PLN_AREA_N;

      const l = layer as unknown as PathLayer;

      layer.on({
        mouseover: () => {
          if (layer === selectedLayerRef.current) return;
          l.setStyle({
            weight: 3,
            fillOpacity: 0.85,
            color: '#222222',
            dashArray: '',
          });
          l.bringToFront();
          onHoverRef.current({ id, name, type: 'subzone', parentId });
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
            dashArray: '',
          });
          l.bringToFront();
          onSelectRef.current({ id, name, type: 'subzone', parentId });
        },
      });
    },
    [], // Stable — reads latest callbacks via refs
  );

  useEffect(() => {
    return () => {
      selectedLayerRef.current = null;
    };
  }, []);

  return (
    <GeoJSON
      ref={geoRef}
      key={`subzone-${data.features.length}`}
      data={data}
      style={getStyle}
      onEachFeature={onEachFeature}
    />
  );
}
