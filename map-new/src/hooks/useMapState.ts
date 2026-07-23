import { useState, useMemo, useEffect } from 'react';
import type { SelectedRegion, ColorMap } from '../lib/types';
import type { PlanningAreaCollection } from '../lib/types';
import { generateColorMap } from '../lib/colors';

type HeatmapScores = Record<string, number>;

interface MapState {
  selectedArea: SelectedRegion | null;
  setSelectedArea: (r: SelectedRegion | null) => void;
  hoveredArea: SelectedRegion | null;
  setHoveredArea: (r: SelectedRegion | null) => void;
  colorMap: ColorMap;
  scoresLoaded: boolean;
}

export function useMapState(planningAreas: PlanningAreaCollection | null): MapState {
  const [selectedArea, setSelectedArea] = useState<SelectedRegion | null>(null);
  const [hoveredArea, setHoveredArea] = useState<SelectedRegion | null>(null);
  const [scores, setScores] = useState<HeatmapScores | null>(null);
  const scoresLoaded = scores !== null;

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}pa-heatmap.json`).then(r => r.json()).then(setScores).catch(() => {});
  }, []);

  const colorMap = useMemo<ColorMap>(() => {
    if (!planningAreas) return new Map();
    const ids = planningAreas.features.map(f => f.properties?.PLN_AREA_N).filter((id): id is string => Boolean(id));
    return generateColorMap([...new Set(ids)], scores);
  }, [planningAreas, scores]);

  return { selectedArea, setSelectedArea, hoveredArea, setHoveredArea, colorMap, scoresLoaded };
}
