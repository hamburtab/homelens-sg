import { useState, useMemo } from 'react';
import type { SelectedRegion, ColorMap } from '../lib/types';
import type { PlanningAreaCollection } from '../lib/types';
import { generateColorMap } from '../lib/colors';

interface MapState {
  selectedArea: SelectedRegion | null;
  setSelectedArea: (r: SelectedRegion | null) => void;
  hoveredArea: SelectedRegion | null;
  setHoveredArea: (r: SelectedRegion | null) => void;
  colorMap: ColorMap;
}

export function useMapState(planningAreas: PlanningAreaCollection | null): MapState {
  const [selectedArea, setSelectedArea] = useState<SelectedRegion | null>(null);
  const [hoveredArea, setHoveredArea] = useState<SelectedRegion | null>(null);

  const colorMap = useMemo<ColorMap>(() => {
    if (!planningAreas) return new Map();
    const ids = planningAreas.features.map(f => f.properties?.PLN_AREA_N).filter((id): id is string => Boolean(id));
    return generateColorMap([...new Set(ids)]);
  }, [planningAreas]);

  return { selectedArea, setSelectedArea, hoveredArea, setHoveredArea, colorMap };
}
