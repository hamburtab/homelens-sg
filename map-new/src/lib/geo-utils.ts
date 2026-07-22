/**
 * Geographic utilities powered by Turf.js
 *
 * Provides coordinate-to-region lookup for both Planning Areas and Subzones.
 */

import booleanPointInPolygon from '@turf/boolean-point-in-polygon';
import { point as turfPoint } from '@turf/helpers';
import centroid from '@turf/centroid';
import type { Feature, FeatureCollection, Polygon, MultiPolygon } from 'geojson';
import type { SelectedRegion, ViewMode } from './types';

// ---- Bounding Box Pre-filter ----

interface BBox {
  minLng: number;
  minLat: number;
  maxLng: number;
  maxLat: number;
}

/** Extract a rough bounding box from a GeoJSON geometry */
function getBBox(geom: Polygon | MultiPolygon): BBox {
  const coords =
    geom.type === 'Polygon'
      ? geom.coordinates[0]
      : geom.coordinates.flatMap((ring) => ring[0]);

  let minLng = Infinity;
  let minLat = Infinity;
  let maxLng = -Infinity;
  let maxLat = -Infinity;

  for (const [lng, lat] of coords) {
    if (lng < minLng) minLng = lng;
    if (lng > maxLng) maxLng = lng;
    if (lat < minLat) minLat = lat;
    if (lat > maxLat) maxLat = lat;
  }

  return { minLng, minLat, maxLng, maxLat };
}

function pointInBBox(lng: number, lat: number, bbox: BBox): boolean {
  return (
    lng >= bbox.minLng &&
    lng <= bbox.maxLng &&
    lat >= bbox.minLat &&
    lat <= bbox.maxLat
  );
}

// ---- Feature with pre-computed BBox ----

interface IndexedFeature {
  feature: Feature<Polygon | MultiPolygon>;
  bbox: BBox;
  name: string;
  id: string;
  parentId?: string;
}

// ---- Main Lookup ----

/**
 * Find the region (Planning Area or Subzone) containing the given coordinates.
 *
 * Uses a two-pass approach for performance:
 *  1. Bounding-box pre-filter (fast, skips ~95% of features)
 *  2. Exact point-in-polygon check via Turf.js (accurate)
 *
 * @param lng - Longitude (WGS84)
 * @param lat - Latitude (WGS84)
 * @param geojson - The currently active GeoJSON FeatureCollection
 * @param mode - 'planning' or 'subzone' (affects which property key is read)
 * @returns SelectedRegion or null if coordinates fall outside all polygons
 */
export function findRegionByCoords(
  lng: number,
  lat: number,
  geojson: FeatureCollection<Polygon | MultiPolygon>,
  mode: ViewMode,
): SelectedRegion | null {
  const testPoint = turfPoint([lng, lat]);

  for (const feature of geojson.features) {
    if (!feature.geometry) continue;

    // Quick bbox rejection
    const bbox = getBBox(feature.geometry as Polygon | MultiPolygon);
    if (!pointInBBox(lng, lat, bbox)) continue;

    // Exact test
    const props = feature.properties as Record<string, string> | null;
    if (!props) continue;

    try {
      if (booleanPointInPolygon(testPoint, feature as Feature<Polygon | MultiPolygon>)) {
        if (mode === 'planning') {
          return {
            id: props.PLN_AREA_N,
            name: props.PLN_AREA_N,
            type: 'planning',
          };
        }
        return {
          id: props.SUBZONE_N,
          name: props.SUBZONE_N,
          type: 'subzone',
          parentId: props.PLN_AREA_N,
        };
      }
    } catch {
      // Skip malformed geometries
      continue;
    }
  }

  return null;
}

/**
 * Build an indexed array of features with pre-computed bboxes for repeated lookups.
 * Call once when GeoJSON loads; use with `findRegionInIndex` for hot-path queries.
 */
export function buildFeatureIndex(
  geojson: FeatureCollection<Polygon | MultiPolygon>,
  mode: ViewMode,
): IndexedFeature[] {
  return geojson.features
    .filter((f) => f.geometry)
    .map((f) => {
      const props = (f.properties ?? {}) as Record<string, string>;
      const bbox = getBBox(f.geometry as Polygon | MultiPolygon);
      return {
        feature: f as Feature<Polygon | MultiPolygon>,
        bbox,
        id: mode === 'planning' ? props.PLN_AREA_N : props.SUBZONE_N,
        name: mode === 'planning' ? props.PLN_AREA_N : props.SUBZONE_N,
        parentId: mode === 'subzone' ? props.PLN_AREA_N : undefined,
      };
    });
}

/**
 * Fast lookup against a pre-built index (use after `buildFeatureIndex`).
 */
export function findRegionInIndex(
  lng: number,
  lat: number,
  index: IndexedFeature[],
  mode: ViewMode,
): SelectedRegion | null {
  const testPoint = turfPoint([lng, lat]);

  for (const entry of index) {
    if (!pointInBBox(lng, lat, entry.bbox)) continue;
    try {
      if (booleanPointInPolygon(testPoint, entry.feature)) {
        return {
          id: entry.id,
          name: entry.name,
          type: mode,
          parentId: entry.parentId,
        };
      }
    } catch {
      continue;
    }
  }

  return null;
}

// Re-export for convenience
export type { IndexedFeature };

/** Convert GeoJSON features to Point centroids (keeps existing Points as-is) */
export function toPointFeatures(fc: GeoJSON.FeatureCollection): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: fc.features.map(f => {
      if (f.geometry?.type === 'Point') return f;
      try {
        const c = centroid(f);
        return { type: 'Feature', properties: f.properties, geometry: c.geometry } as GeoJSON.Feature;
      } catch { return f; }
    }),
  };
}
