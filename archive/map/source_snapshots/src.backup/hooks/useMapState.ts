/**
 * Core map state hook.
 *
 * Owns:
 *  - viewMode  (planning | subzone)
 *  - selectedArea
 *  - hoveredArea
 *  - colorMap   (stable Map<planningAreaId, HSL>)
 *
 * Designed to sit inside <SingaporeMap> and feed props down to children.
 */

import { useState, useMemo, useCallback } from 'react';
import type { ViewMode, SelectedRegion, ColorMap } from '../lib/types';
import type { PlanningAreaCollection } from '../lib/types';
import { generateColorMap } from '../lib/colors';

interface MapState {
  viewMode: ViewMode;
  setViewMode: (mode: ViewMode) => void;
  selectedArea: SelectedRegion | null;
  setSelectedArea: (region: SelectedRegion | null) => void;
  hoveredArea: SelectedRegion | null;
  setHoveredArea: (region: SelectedRegion | null) => void;
  colorMap: ColorMap;
}

export function useMapState(
  planningAreas: PlanningAreaCollection | null,
  defaultView: ViewMode = 'planning',
): MapState {
  const [viewMode, setViewMode] = useState<ViewMode>(defaultView);
  const [selectedArea, setSelectedArea] = useState<SelectedRegion | null>(null);
  const [hoveredArea, setHoveredArea] = useState<SelectedRegion | null>(null);

  // Build colour map once when planning areas load
  const colorMap = useMemo<ColorMap>(() => {
    if (!planningAreas) return new Map();
    const ids = planningAreas.features
      .map((f) => f.properties?.PLN_AREA_N)
      .filter((id): id is string => Boolean(id));
    return generateColorMap([...new Set(ids)]);
  }, [planningAreas]);

  // When switching views, clear selection
  const handleViewModeChange = useCallback((mode: ViewMode) => {
    setViewMode(mode);
    setSelectedArea(null);
    setHoveredArea(null);
  }, []);

  return {
    viewMode,
    setViewMode: handleViewModeChange,
    selectedArea,
    setSelectedArea,
    hoveredArea,
    setHoveredArea,
    colorMap,
  };
}
