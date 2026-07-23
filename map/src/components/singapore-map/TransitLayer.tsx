import { useEffect, useState, useRef } from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';
import type { Feature, FeatureCollection } from 'geojson';
import type { LayerCategory, FocusState } from '../../lib/types';
import { useLayerData } from '../../hooks/useLayerData';
import centroid from '@turf/centroid';
import bbox from '@turf/bbox';

const TRANSIT = new Set(['railway_station', 'bus_stop']);
const CANVAS = L.canvas({ padding: 0.5 });
const ICON_ZOOM = 14;

interface P {
  activeIds: Set<string>;
  categories: LayerCategory[];
  onFocus: (s: FocusState) => void;
  onSelectFeature: (f: Feature, l: string) => void;
}

function fname(f: Feature) {
  return (f.properties?.['name'] || f.properties?.['name:en'] || '') as string;
}

export function TransitLayer({ activeIds, categories, onFocus, onSelectFeature }: P) {
  const map = useMap();
  const { load, cacheRef } = useLayerData();
  const [loaded, setLoaded] = useState<Map<string, FeatureCollection>>(new Map());
  const [zoom, setZoom] = useState(map.getZoom());
  const layerRef = useRef<L.GeoJSON | null>(null);

  useEffect(() => {
    const updateZoom = () => setZoom(map.getZoom());
    map.on('zoomend', updateZoom);
    return () => { map.off('zoomend', updateZoom); };
  }, [map]);

  useEffect(() => {
    for (const category of categories.filter((item) => activeIds.has(item.id) && TRANSIT.has(item.id))) {
      if (loaded.has(category.id)) continue;
      if (cacheRef.current.has(category.dataSource)) {
        setLoaded((previous) => new Map(previous).set(category.id, cacheRef.current.get(category.dataSource)!));
      } else {
        load(category.dataSource).then((data) => {
          if (data) setLoaded((previous) => new Map(previous).set(category.id, data));
        });
      }
    }
  }, [activeIds, categories, load, loaded, cacheRef]);

  useEffect(() => {
    if (layerRef.current) {
      map.removeLayer(layerRef.current);
      layerRef.current = null;
    }

    const features: Feature[] = [];
    for (const [categoryId, data] of loaded) {
      if (!activeIds.has(categoryId) || !TRANSIT.has(categoryId)) continue;
      const category = categories.find((item) => item.id === categoryId);
      if (!category) continue;
      for (const feature of data.features) {
        let pointFeature = feature;
        if (feature.geometry?.type !== 'Point') {
          try {
            const center = centroid(feature);
            pointFeature = { type: 'Feature', properties: feature.properties, geometry: center.geometry } as Feature;
          } catch {
            continue;
          }
        }
        (pointFeature as any)._cid = categoryId;
        (pointFeature as any)._color = category.color;
        (pointFeature as any)._icon = category.icon;
        features.push(pointFeature);
      }
    }
    if (!features.length) return;

    const showIcons = zoom >= ICON_ZOOM;
    const geoJsonLayer = L.geoJSON({ type: 'FeatureCollection', features } as FeatureCollection, {
      pointToLayer: (feature, latLng) => {
        const color = (feature as any)._color;
        const icon = (feature as any)._icon;
        const name = fname(feature);
        if (showIcons && name) {
          const label = name.length > 14 ? `${name.slice(0, 12)}...` : name;
          const html = `<div class="osm-marker" style="--marker-color:${color}"><div class="osm-marker__dot">${icon}</div><div class="osm-marker__label">${label}</div></div>`;
          const divIcon = L.divIcon({ html, className: 'osm-marker-container', iconSize: [68, 40], iconAnchor: [34, 40] });
          const marker = L.marker(latLng, { icon: divIcon });
          (marker as any)._feature = feature;
          (marker as any)._cid = (feature as any)._cid;
          return marker;
        }
        const marker = L.circleMarker(latLng, {
          radius: 5,
          fillColor: color,
          color: 'transparent',
          weight: 0,
          fillOpacity: 0.75,
          renderer: CANVAS,
        });
        if (name) marker.bindTooltip(name, { direction: 'top', offset: [0, -6], opacity: 0.9 });
        (marker as any)._feature = feature;
        (marker as any)._cid = (feature as any)._cid;
        return marker;
      },
    });

    geoJsonLayer.on('click', (event: any) => {
      const feature = (event.layer as any)._feature as Feature | undefined;
      if (!feature) return;
      const category = categories.find((item) => item.id === (event.layer as any)._cid);
      try {
        const bounds = bbox(feature);
        onFocus({ bounds: [[bounds[1], bounds[0]], [bounds[3], bounds[2]]], label: fname(feature) || category?.label || '' });
      } catch {}
      onSelectFeature(feature, category?.label ?? '');
    });

    geoJsonLayer.addTo(map);
    layerRef.current = geoJsonLayer;
    return () => {
      if (layerRef.current) {
        map.removeLayer(layerRef.current);
        layerRef.current = null;
      }
    };
  }, [loaded, activeIds, zoom, map, categories, onFocus, onSelectFeature]);

  return null;
}
