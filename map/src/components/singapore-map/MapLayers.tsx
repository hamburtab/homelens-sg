import { useEffect, useRef } from 'react';
import { TileLayer, useMap } from 'react-leaflet';
import type { Feature } from 'geojson';
import type { Polygon, MultiPolygon } from 'geojson';
import type { SelectedRegion, FocusState } from '../../lib/types';
import { ALL_CATEGORIES } from '../../lib/osm-config';
import { PlanningAreaLayer } from './PlanningAreaLayer';
import { SubzoneLayer } from './SubzoneLayer';
import { MarkerLayer } from './MarkerLayer';
import { TransitLayer } from './TransitLayer';
import { FocusMask } from './FocusMask';
import { RentalMarkers } from './RentalMarkers';
import bbox from '@turf/bbox';

const STREET = 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png';
const SAT = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
const ATTR = '&copy; OSM &copy; CARTO | Sat: Esri';

type FGeom = Feature<Polygon | MultiPolygon> | null;

interface P {
  planningAreas: any; subzones: any; colorMap: any; selectedArea: any;
  drillPA: string | null; drillSZ: string | null;
  focusGeom: FGeom; maskGeom: FGeom; focusState: FocusState | null;
  activeCats: Set<string>; satellite: boolean;
  filteredListings: any[]; selectedListingId: string | null;
  onSelectPA: (r: SelectedRegion) => void; onHoverPA: (r: SelectedRegion | null) => void;
  onFocusSZ: (id: string, f: Feature) => void; onClear: () => void;
  onSelectListing: (l: any) => void;
  onSelectOsm: (f: Feature, l: string) => void;
}

export function MapLayers(p: P) {
  const map = useMap();
  const prev = useRef({ pa: null as string | null, sz: null as string | null });

  useEffect(() => {
    if (p.drillSZ && p.drillSZ !== prev.current.sz && p.focusGeom) {
      try { const b = bbox(p.focusGeom); map.fitBounds([[b[1],b[0]],[b[3],b[2]]], { padding:[40,40], maxZoom:16 }); } catch {}
    } else if (p.drillPA && p.drillPA !== prev.current.pa && p.focusGeom) {
      try { const b = bbox(p.focusGeom); map.fitBounds([[b[1],b[0]],[b[3],b[2]]], { padding:[30,30], maxZoom:14 }); } catch {}
    }
    prev.current = { pa: p.drillPA, sz: p.drillSZ };
  }, [p.drillPA, p.drillSZ, p.focusGeom, map]);

  return (
    <>
      <TileLayer url={p.satellite ? SAT : STREET} attribution={ATTR} />
      {!p.drillPA && p.planningAreas && <PlanningAreaLayer data={p.planningAreas} colorMap={p.colorMap} selectedArea={p.selectedArea} onSelect={p.onSelectPA} onHover={p.onHoverPA} />}
      {p.drillPA && p.subzones && p.colorMap.size > 0 && (
        <SubzoneLayer data={p.subzones} colorMap={p.colorMap} selectedArea={p.selectedArea} onSelect={p.onSelectPA} onHover={p.onHoverPA}
          onFocusSubzone={p.onFocusSZ} filterParentId={p.drillSZ ? undefined : p.drillPA} outlineOnly={!p.drillSZ} />
      )}
      <MarkerLayer activeIds={p.activeCats} categories={ALL_CATEGORIES} onFocus={() => {}} onSelectFeature={p.onSelectOsm} focusGeometry={p.drillSZ ? p.focusGeom : null} />
      <TransitLayer activeIds={p.activeCats} categories={ALL_CATEGORIES} onFocus={() => {}} onSelectFeature={p.onSelectOsm} />
      {p.drillPA && <FocusMask focus={p.focusState} focusGeometry={p.maskGeom} onClear={p.onClear} />}
      {p.filteredListings.length > 0 && <RentalMarkers listings={p.filteredListings} selectedId={p.selectedListingId} onSelect={p.onSelectListing} />}
    </>
  );
}
