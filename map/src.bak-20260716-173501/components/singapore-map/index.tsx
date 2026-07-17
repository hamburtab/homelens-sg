import { useCallback, useMemo, useState, useRef, useEffect } from 'react';
import { MapContainer, TileLayer, useMap } from 'react-leaflet';
import type { Feature } from 'geojson';
import type { Polygon, MultiPolygon } from 'geojson';
import type { SingaporeMapProps, SelectedRegion, FocusState } from '../../lib/types';
import { OSM_GROUPS, ALL_CATEGORIES } from '../../lib/osm-config';
import { useGeoJson } from '../../hooks/useGeoJson';
import { useMapState } from '../../hooks/useMapState';
import { useRentalListings, useFilteredListings } from '../../hooks/useRentalListings';
import { PlanningAreaLayer } from './PlanningAreaLayer';
import { SubzoneLayer } from './SubzoneLayer';
import { RentalMarkers } from './RentalMarkers';
import { RentalDetailPanel } from './RentalDetailPanel';
import { LayerPanel } from './LayerPanel';
import { MarkerLayer } from './MarkerLayer';
import { FocusMask } from './FocusMask';
import { OsmDetailPanel } from './OsmDetailPanel';
import bbox from '@turf/bbox';

const SG: [number, number] = [1.3521, 103.8198];
const STREET = 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png';
const SAT = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
const ATTR = '&copy; OSM &copy; CARTO | Sat: Esri';

type FGeom = Feature<Polygon | MultiPolygon> | null;

function MapInner(p: any) {
  const map = useMap();
  const prev = useRef({ pa: null as string | null, sz: null as string | null });
  useEffect(() => {
    if (p.drillSZ && p.drillSZ !== prev.current.sz && p.focusGeom) {
      try { const b = bbox(p.focusGeom); map.fitBounds([[b[1],b[0]],[b[3],b[2]]], { padding: [40,40], maxZoom:16 }); } catch {}
    } else if (p.drillPA && p.drillPA !== prev.current.pa && p.focusGeom) {
      try { const b = bbox(p.focusGeom); map.fitBounds([[b[1],b[0]],[b[3],b[2]]], { padding: [30,30], maxZoom:14 }); } catch {}
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
      {p.drillPA && <FocusMask focus={p.focusState} focusGeometry={p.maskGeom} onClear={p.onClear} />}
      {p.filteredListings.length > 0 && <RentalMarkers listings={p.filteredListings} selectedId={p.selectedListingId} onSelect={p.onSelectListing} />}
    </>
  );
}

export function SingaporeMap({ onSelect, onHover, className, listingsUrl, listingFilter, listingSort, listingLabelMap }: SingaporeMapProps) {
  const { planningAreas, subzones, loading, error } = useGeoJson();
  const { listings } = useRentalListings(listingsUrl);
  const filtered = useFilteredListings(listings, listingFilter, listingSort);
  const [selListing, setSelListing] = useState<any>(null);
  const { selectedArea, setSelectedArea, setHoveredArea, colorMap } = useMapState(planningAreas);
  const [drillPA, setDrillPA] = useState<string | null>(null);
  const [drillSZ, setDrillSZ] = useState<string | null>(null);
  const [focusGeom, setFocusGeom] = useState<FGeom>(null);
  const [maskGeom, setMaskGeom] = useState<FGeom>(null);
  const [focusState, setFocusState] = useState<FocusState | null>(null);
  const [activeCats, setActiveCats] = useState<Set<string>>(new Set());
  const [osmFeat, setOsmFeat] = useState<Feature | null>(null);
  const [osmLabel, setOsmLabel] = useState('');
  const [satellite, setSatellite] = useState(false);

  const findPA = useCallback((paId: string): FGeom => {
    const f = planningAreas?.features.find(x => x.properties?.PLN_AREA_N === paId);
    return f?.geometry ? { type:'Feature', properties:{}, geometry:f.geometry } as FGeom : null;
  }, [planningAreas]);

  const hSelectPA = useCallback((r: SelectedRegion) => {
    setSelectedArea(r); setDrillPA(r.id); setDrillSZ(null);
    const g = findPA(r.id); setFocusGeom(g); setMaskGeom(g);
    try { if (g) { const b = bbox(g); setFocusState({ bounds:[[b[1],b[0]],[b[3],b[2]]], label:r.name }); } } catch {}
    onSelect?.(r);
  }, [onSelect, setSelectedArea, findPA]);

  const hHoverPA = useCallback((r: SelectedRegion | null) => { setHoveredArea(r); onHover?.(r); }, [onHover, setHoveredArea]);

  const hFocusSZ = useCallback((id: string, f: Feature) => {
    setDrillSZ(id);
    const g = { type:'Feature', properties:{}, geometry:f.geometry } as FGeom;
    setFocusGeom(g); setOsmFeat(null);
    try { const b = bbox(f); setFocusState({ bounds:[[b[1],b[0]],[b[3],b[2]]], label:id }); } catch {}
  }, []);

  const hClear = useCallback(() => {
    if (drillSZ) { setDrillSZ(null); setFocusGeom(drillPA ? findPA(drillPA) : null); setFocusState(null); setOsmFeat(null); }
    else if (drillPA) { setDrillPA(null); setFocusGeom(null); setMaskGeom(null); setFocusState(null); }
  }, [drillSZ, drillPA, findPA]);

  const tog = useCallback((id: string) => setActiveCats(p => { const n = new Set(p); n.has(id)?n.delete(id):n.add(id); return n; }), []);
  const togG = useCallback((gid: string, sel: boolean) => {
    const g = OSM_GROUPS.find(x => x.id === gid); if (!g) return;
    setActiveCats(p => { const n = new Set(p); for (const c of g.categories) sel?n.add(c.id):n.delete(c.id); return n; });
  }, []);

  if (error) return <div className="sg-map sg-map--error"><p>Failed to load map data: {error}</p></div>;

  return (
    <div className={`sg-map ${className ?? ''}`}>
      {loading && <div className="sg-map__loading"><div className="sg-map__spinner" /><span>Loading...</span></div>}
      <MapContainer center={SG} zoom={11} minZoom={10} maxZoom={18} className="sg-map__container">
        <MapInner planningAreas={planningAreas} subzones={subzones} colorMap={colorMap} selectedArea={selectedArea}
          drillPA={drillPA} drillSZ={drillSZ} focusGeom={focusGeom} maskGeom={maskGeom} focusState={focusState}
          activeCats={activeCats} satellite={satellite} filteredListings={filtered} selectedListingId={selListing?.id ?? null}
          onSelectPA={hSelectPA} onHoverPA={hHoverPA} onFocusSZ={hFocusSZ} onClear={hClear}
          onSelectListing={setSelListing} onSelectOsm={(f: Feature, l: string) => { setOsmFeat(f); setOsmLabel(l); }} />
      </MapContainer>
      <button className="basemap-toggle" onClick={() => setSatellite(s => !s)}>{satellite ? '🗺️ 街道' : '🛰️ 卫星'}</button>
      <LayerPanel groups={OSM_GROUPS} active={activeCats} onToggle={tog} onToggleGroup={togG} />
      <RentalDetailPanel listing={selListing} onClose={() => setSelListing(null)} labelMap={listingLabelMap} />
      <OsmDetailPanel feature={osmFeat} categoryLabel={osmLabel} onClose={() => setOsmFeat(null)} />
      {(drillPA || drillSZ) && (
        <div className="drill-banner"><span>{drillSZ ? `📍 ${drillSZ}` : `📍 ${drillPA} — 点击子区深入查看`}</span>
          <button onClick={hClear}>{drillSZ ? '← 返回子区列表' : '← 返回全岛视图'}</button></div>
      )}
    </div>
  );
}
export type { SingaporeMapProps, SelectedRegion, RentalListing, ListingLabelMap } from '../../lib/types';
export { findRegionByCoords, buildFeatureIndex, findRegionInIndex } from '../../lib/geo-utils';
export { generateColorMap } from '../../lib/colors';
