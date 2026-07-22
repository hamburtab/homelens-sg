import { useEffect, useRef, useState } from 'react';
import { TileLayer, useMap, GeoJSON } from 'react-leaflet';
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

const STREET = 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png';
const SAT = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
const ATTR = '&copy; OSM &copy; CARTO | Sat: Esri';

import type { PlanningAreaCollection, SubzoneCollection, ColorMap, RentalListing } from '../../lib/types';

type FGeom = Feature<Polygon | MultiPolygon> | null;

interface MapLayersProps {
  planningAreas: PlanningAreaCollection | null;
  subzones: SubzoneCollection | null;
  colorMap: ColorMap;
  selectedArea: SelectedRegion | null;
  drillPA: string | null; drillSZ: string | null;
  focusGeom: FGeom; maskGeom: FGeom; focusState: FocusState | null;
  activeCats: Set<string>; satellite: boolean;
  filteredListings: RentalListing[]; selectedListingId: string | null;
  onSelectPA: (r: SelectedRegion) => void; onHoverPA: (r: SelectedRegion | null) => void;
  onFocusSZ: (id: string, f: Feature) => void; onClear: () => void;
  onSelectListing: (l: RentalListing | null) => void;
  onSelectOsm: (f: Feature, l: string) => void;
  scoresLoaded: boolean;
  showHeatmap: boolean;
  showLabels: boolean;
  freeMode: boolean;
}

export function MapLayers(p: MapLayersProps) {
  const map = useMap();
  const prev = useRef({ pa: null as string | null, sz: null as string | null });

  const [sgMask, setSgMask] = useState<any>(null);

  // Create high-z-index pane for focus mask so it renders above markers (markerPane=600)
  useEffect(() => {
    if (!map.getPane('focusMask')) {
      map.createPane('focusMask');
      map.getPane('focusMask')!.style.zIndex = '650';
      map.getPane('focusMask')!.style.pointerEvents = 'auto';
    }
    if (!map.getPane('sgMask')) {
      map.createPane('sgMask');
      map.getPane('sgMask')!.style.zIndex = '300';
      map.getPane('sgMask')!.style.pointerEvents = 'none';
    }
    // Load Singapore border mask
    fetch(`${import.meta.env.BASE_URL}sg-mask.geojson`).then(r => r.json()).then(d => setSgMask(d)).catch(() => {});
  }, [map]);

  useEffect(() => {
    if (p.drillSZ && p.drillSZ !== prev.current.sz && p.focusGeom) {
      try { const b = bbox(p.focusGeom); map.fitBounds([[b[1],b[0]],[b[3],b[2]]], { padding:[60,60], maxZoom:16 }); } catch { console.warn('fitBounds failed'); }
    } else if (p.drillPA && p.drillPA !== prev.current.pa && p.focusGeom) {
      try { const b = bbox(p.focusGeom); map.fitBounds([[b[1],b[0]],[b[3],b[2]]], { padding:[30,30], maxZoom:15 }); } catch { console.warn('fitBounds failed'); }
    }
    prev.current = { pa: p.drillPA, sz: p.drillSZ };
  }, [p.drillPA, p.drillSZ, p.focusGeom, map]);

  return (
    <>
      <TileLayer url={p.satellite ? SAT : STREET} attribution={ATTR} />
      {sgMask && <GeoJSON key="sg-mask" data={sgMask} style={{ fillColor:'#111', fillOpacity: p.satellite ? 0.65 : 0.50, color:'transparent', weight:0 }} interactive={false} />}
      {!p.drillPA && !p.freeMode && p.planningAreas && p.scoresLoaded && <PlanningAreaLayer data={p.planningAreas} colorMap={p.colorMap} selectedArea={p.selectedArea} onSelect={p.onSelectPA} onHover={p.onHoverPA} showHeatmap={p.showHeatmap} />}
      {p.drillPA && p.subzones && (
        <SubzoneLayer data={p.subzones} colorMap={p.colorMap} selectedArea={p.selectedArea} onSelect={p.onSelectPA} onHover={p.onHoverPA}
          onFocusSubzone={p.onFocusSZ} filterParentId={p.drillPA} outlineOnly={!p.drillSZ} />
      )}
      <MarkerLayer activeIds={p.activeCats} categories={ALL_CATEGORIES} onFocus={() => {}} onSelectFeature={p.onSelectOsm} focusGeometry={p.drillPA ? p.maskGeom : null} showLabels={p.showLabels} />
      {p.drillPA && <TransitLayer activeIds={p.activeCats} categories={ALL_CATEGORIES} onFocus={() => {}} onSelectFeature={p.onSelectOsm} drillPA={p.drillPA} />}
      {p.drillPA && <FocusMask focus={p.focusState} focusGeometry={p.maskGeom} onClear={p.onClear} />}
      {p.filteredListings.length > 0 && <RentalMarkers listings={p.filteredListings} selectedId={p.selectedListingId} onSelect={p.onSelectListing} />}
    </>
  );
}
