/**
 * GeoJSON data loading hook with per-session cache.
 * Two-phase: planning-areas first (unblocks spinner), subzones deferred (background).
 */
import { useState, useEffect } from 'react';
import type { PlanningAreaCollection, SubzoneCollection } from '../lib/types';

let planningCache: PlanningAreaCollection | null = null;
let subzoneCache: SubzoneCollection | null = null;

interface UseGeoJsonResult {
  planningAreas: PlanningAreaCollection | null;
  subzones: SubzoneCollection | null;
  loading: boolean;   // only blocked by planning-areas
  subzonesLoading: boolean;
  error: string | null;
}

export function useGeoJson(): UseGeoJsonResult {
  const [planningAreas, setPlanningAreas] = useState<PlanningAreaCollection | null>(planningCache);
  const [subzones, setSubzones] = useState<SubzoneCollection | null>(subzoneCache);
  const [loading, setLoading] = useState(!planningCache);
  const [subzonesLoading, setSubzonesLoading] = useState(!subzoneCache);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const base = import.meta.env.BASE_URL;
    let cancelled = false;

    // Phase 1: planning-areas first (critical path)
    async function fetchPlanning() {
      if (planningCache) {
        if (!cancelled) setLoading(false);
        return;
      }
      try {
        const r = await fetch(`${base}planning-areas.geojson`);
        if (!r.ok) throw new Error(`planning-areas HTTP ${r.status}`);
        planningCache = await r.json() as PlanningAreaCollection;
        if (!cancelled) { setPlanningAreas(planningCache); setLoading(false); }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load planning-areas');
          setLoading(false);
        }
      }
    }

    // Phase 2: subzones deferred (background)
    async function fetchSubzones() {
      if (subzoneCache) {
        if (!cancelled) setSubzonesLoading(false);
        return;
      }
      try {
        const r = await fetch(`${base}subzones.geojson`);
        if (!r.ok) throw new Error(`subzones HTTP ${r.status}`);
        subzoneCache = await r.json() as SubzoneCollection;
        if (!cancelled) { setSubzones(subzoneCache); setSubzonesLoading(false); }
      } catch {
        // Subzones are non-critical — silently degrade
        if (!cancelled) setSubzonesLoading(false);
      }
    }

    fetchPlanning();
    // Defer subzones — start after planning-areas resolves or at least 200ms
    const timer = setTimeout(fetchSubzones, planningCache ? 0 : 500);

    return () => { cancelled = true; clearTimeout(timer); };
  }, []);

  return { planningAreas, subzones, loading, subzonesLoading, error };
}
