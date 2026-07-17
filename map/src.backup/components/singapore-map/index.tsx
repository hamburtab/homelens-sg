/**
 * SingaporeMap — Main exported component.
 *
 * Embeds an interactive Leaflet map with dual-view support for
 * Singapore Planning Areas (Level 1) and Subzones (Level 2).
 *
 * Public API:
 *   <SingaporeMap onSelect={fn} onHover={fn} defaultView="planning" />
 *
 * Utilities (also exported):
 *   findRegionByCoords(lng, lat, geojson, mode) → SelectedRegion | null
 */

import { useCallback, useMemo, useState } from 'react';
import { MapContainer, TileLayer } from 'react-leaflet';
import type { SingaporeMapProps, SelectedRegion, ViewMode, RentalListing } from '../../lib/types';

import { useGeoJson } from '../../hooks/useGeoJson';
import { useMapState } from '../../hooks/useMapState';
import { useRentalListings, useFilteredListings } from '../../hooks/useRentalListings';
import { ViewSwitcher } from './ViewSwitcher';
import { SelectedInfoPanel } from './SelectedInfoPanel';
import { PlanningAreaLayer } from './PlanningAreaLayer';
import { SubzoneLayer } from './SubzoneLayer';
import { RentalMarkers } from './RentalMarkers';
import { RentalDetailPanel } from './RentalDetailPanel';
import { Legend } from './Legend';

// Singapore centre (approx)
const SG_CENTER: [number, number] = [1.3521, 103.8198];
const SG_ZOOM = 11;
const MIN_ZOOM = 10;
const MAX_ZOOM = 18;

// CartoDB Positron — clean light basemap
const TILE_URL =
  'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png';
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>';

export function SingaporeMap({
  onSelect,
  onHover,
  defaultView = 'planning',
  className,
  listingsUrl,
  listingFilter,
  listingSort,
  listingLabelMap,
}: SingaporeMapProps) {
  // ---- Data ----
  const { planningAreas, subzones, loading, error } = useGeoJson();

  // ---- Rental listings ----
  const { listings } = useRentalListings(listingsUrl);
  const filteredListings = useFilteredListings(listings, listingFilter, listingSort);
  const [selectedListing, setSelectedListing] = useState<RentalListing | null>(null);

  // ---- State ----
  const {
    viewMode,
    setViewMode,
    selectedArea,
    setSelectedArea,
    setHoveredArea,
    colorMap,
  } = useMapState(planningAreas, defaultView);

  // ---- Event handlers with external callbacks ----
  const handleSelect = useCallback(
    (region: SelectedRegion) => {
      setSelectedArea(region);
      setSelectedListing(null); // Deselect listing when region clicked
      onSelect?.(region);
    },
    [onSelect, setSelectedArea],
  );

  const handleHover = useCallback(
    (region: SelectedRegion | null) => {
      setHoveredArea(region);
      onHover?.(region);
    },
    [onHover, setHoveredArea],
  );

  // Notify parent when view switches (clears selection/hover)
  const handleViewSwitch = useCallback(
    (mode: ViewMode) => {
      setViewMode(mode);
      setSelectedListing(null);
      onHover?.(null);
    },
    [setViewMode, onHover],
  );

  // ---- Memoize layer content to avoid flicker on re-render ----
  const activeLayer = useMemo(() => {
    if (viewMode === 'planning' && planningAreas) {
      return (
        <PlanningAreaLayer
          data={planningAreas}
          colorMap={colorMap}
          selectedArea={selectedArea}
          onSelect={handleSelect}
          onHover={handleHover}
        />
      );
    }
    if (viewMode === 'subzone' && subzones && colorMap.size > 0) {
      return (
        <SubzoneLayer
          data={subzones}
          colorMap={colorMap}
          selectedArea={selectedArea}
          onSelect={handleSelect}
          onHover={handleHover}
        />
      );
    }
    return null;
  }, [viewMode, planningAreas, subzones, colorMap, selectedArea, handleSelect, handleHover]);

  // ---- Loading / Error states ----
  if (error) {
    return (
      <div className="sg-map sg-map--error">
        <p>Failed to load map data: {error}</p>
        <p className="sg-map__hint">
          Ensure <code>planning-areas.geojson</code> and{' '}
          <code>subzones.geojson</code> are placed in the <code>public/</code>{' '}
          directory.
        </p>
      </div>
    );
  }

  return (
    <div className={`sg-map ${className ?? ''}`}>
      {loading && (
        <div className="sg-map__loading">
          <div className="sg-map__spinner" />
          <span>Loading Singapore map data…</span>
        </div>
      )}

      <MapContainer
        center={SG_CENTER}
        zoom={SG_ZOOM}
        minZoom={MIN_ZOOM}
        maxZoom={MAX_ZOOM}
        className="sg-map__container"
        zoomControl={true}
        attributionControl={true}
      >
        {/* Basemap */}
        <TileLayer url={TILE_URL} attribution={TILE_ATTRIBUTION} />

        {/* Active GeoJSON layer */}
        {activeLayer}

        {/* Rental listing markers (above GeoJSON layer) */}
        {filteredListings.length > 0 && (
          <RentalMarkers
            listings={filteredListings}
            selectedId={selectedListing?.id ?? null}
            onSelect={setSelectedListing}
          />
        )}
      </MapContainer>

      {/* UI Overlays */}
      <ViewSwitcher value={viewMode} onChange={handleViewSwitch} />
      <SelectedInfoPanel region={selectedArea} />
      <RentalDetailPanel
        listing={selectedListing}
        onClose={() => setSelectedListing(null)}
        labelMap={listingLabelMap}
      />
      <Legend colorMap={colorMap} />
    </div>
  );
}

// ---- Public API re-exports ----
export type {
  SingaporeMapProps,
  SelectedRegion,
  ViewMode,
  RentalListing,
  ListingLabelMap,
} from '../../lib/types';

export { findRegionByCoords, buildFeatureIndex, findRegionInIndex } from '../../lib/geo-utils';
export { generateColorMap } from '../../lib/colors';
