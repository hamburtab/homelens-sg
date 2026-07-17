import { useCallback, useState } from 'react';
import { MapContainer } from 'react-leaflet';
import type { Feature } from 'geojson';
import type { Polygon, MultiPolygon } from 'geojson';
import type { SingaporeMapProps, SelectedRegion, FocusState } from '../../lib/types';
import { OSM_GROUPS } from '../../lib/osm-config';
import { useGeoJson } from '../../hooks/useGeoJson';
import { useMapState } from '../../hooks/useMapState';
import { useRentalListings, useFilteredListings } from '../../hooks/useRentalListings';
import { MapLayers } from './MapLayers';
import { LayerPanel } from './LayerPanel';
import { RentalDetailPanel } from './RentalDetailPanel';
import { OsmDetailPanel } from './OsmDetailPanel';
import bbox from '@turf/bbox';

const SG: [number, number] = [1.3521, 103.8198];
type FGeom = Feature<Polygon | MultiPolygon> | null;

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
    setDrillSZ(id); setOsmFeat(null);
    const g = { type:'Feature', properties:{}, geometry:f.geometry } as FGeom; setFocusGeom(g);
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
        <MapLayers
          planningAreas={planningAreas} subzones={subzones} colorMap={colorMap} selectedArea={selectedArea}
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
