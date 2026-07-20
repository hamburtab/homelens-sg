/**
 * GeoJSON data loading hook with per-session cache.
 *
 * Loads planning-areas.geojson and subzones.geojson from /public.
 * Caches in module scope so re-mounts within the same SPA session
 * don't re-fetch.
 */

import { useState, useEffect } from 'react';
import type {
  PlanningAreaCollection,
  SubzoneCollection,
} from '../lib/types';

// ---- Module-level cache (survives component unmounts) ----

let planningCache: PlanningAreaCollection | null = null;
let subzoneCache: SubzoneCollection | null = null;

// ---- Hook ----

interface UseGeoJsonResult {
  planningAreas: PlanningAreaCollection | null;
  subzones: SubzoneCollection | null;
  loading: boolean;
  error: string | null;
}

export function useGeoJson(): UseGeoJsonResult {
  const [planningAreas, setPlanningAreas] =
    useState<PlanningAreaCollection | null>(planningCache);
  const [subzones, setSubzones] = useState<SubzoneCollection | null>(
    subzoneCache,
  );
  const [loading, setLoading] = useState(
    !planningCache || !subzoneCache,
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // If already cached, skip fetch
    if (planningCache && subzoneCache) {
      setLoading(false);
      return;
    }

    let cancelled = false;

    async function fetchBoth() {
      try {
        const base = import.meta.env.BASE_URL;
        const [planResp, subResp] = await Promise.all([
          fetch(`${base}planning-areas.geojson`),
          fetch(`${base}subzones.geojson`),
        ]);

        if (!planResp.ok) {
          throw new Error(
            `Failed to load planning-areas.geojson (HTTP ${planResp.status})`,
          );
        }
        if (!subResp.ok) {
          throw new Error(
            `Failed to load subzones.geojson (HTTP ${subResp.status})`,
          );
        }

        const [planData, subData] = (await Promise.all([
          planResp.json(),
          subResp.json(),
        ])) as [PlanningAreaCollection, SubzoneCollection];

        // Persist in module cache
        planningCache = planData;
        subzoneCache = subData;

        if (!cancelled) {
          setPlanningAreas(planData);
          setSubzones(subData);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : 'Unknown error loading GeoJSON',
          );
          setLoading(false);
        }
      }
    }

    fetchBoth();

    return () => {
      cancelled = true;
    };
  }, []);

  return { planningAreas, subzones, loading, error };
}
