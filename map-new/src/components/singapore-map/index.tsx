import { useCallback, useState, useEffect } from 'react';
import { MapContainer } from 'react-leaflet';
import type { Feature } from 'geojson';
import type { Polygon, MultiPolygon } from 'geojson';
import type { SingaporeMapProps, SelectedRegion, FocusState, Lang, RentalListing } from '../../lib/types';
import { OSM_GROUPS } from '../../lib/osm-config';
import { useGeoJson } from '../../hooks/useGeoJson';
import { useMapState } from '../../hooks/useMapState';
import { useRentalListings, useFilteredListings } from '../../hooks/useRentalListings';
import { MapLayers } from './MapLayers';
import { LayerPanel } from './LayerPanel';
import { RegionPanel, type DrillLevel } from './RegionPanel';
import { RentalDetailPanel } from './RentalDetailPanel';
import { OsmDetailPanel } from './OsmDetailPanel';
import bbox from '@turf/bbox';
import { useMap } from 'react-leaflet';

function ZoomDebug({ onZoom }: { onZoom: (z: number) => void }) {
  const map = useMap();
  useEffect(() => {
    onZoom(map.getZoom());
    const f = () => onZoom(map.getZoom());
    map.on('zoomend', f);
    return () => { map.off('zoomend', f); };
  }, [map, onZoom]);
  return null;
}

const SG: [number, number] = [1.3521, 103.8198];
type FGeom = Feature<Polygon | MultiPolygon> | null;

export function SingaporeMap({ onSelect, onHover, className, listingsUrl, listingFilter, listingSort, listingLabelMap }: SingaporeMapProps) {
  const { planningAreas, subzones, loading, error } = useGeoJson();
  const { listings } = useRentalListings(listingsUrl);
  const filtered = useFilteredListings(listings, listingFilter, listingSort);
  const [selListing, setSelListing] = useState<RentalListing | null>(null);
  const hSelectOsm = useCallback((f: Feature, l: string) => { setOsmFeat(f); setOsmLabel(l); }, []);
  const { selectedArea, setSelectedArea, setHoveredArea, colorMap, scoresLoaded } = useMapState(planningAreas);

  const [drillPA, setDrillPA] = useState<string | null>(null);
  const [drillSZ, setDrillSZ] = useState<string | null>(null);
  const [focusGeom, setFocusGeom] = useState<FGeom>(null);
  const [maskGeom, setMaskGeom] = useState<FGeom>(null);
  const [focusState, setFocusState] = useState<FocusState | null>(null);
  const [activeCats, setActiveCats] = useState<Set<string>>(new Set());
  const [osmFeat, setOsmFeat] = useState<Feature | null>(null);
  const [osmLabel, setOsmLabel] = useState('');
  const [satellite, setSatellite] = useState(false);
  const [debugZoom, setDebugZoom] = useState(11);
  const [showHeatmap, setShowHeatmap] = useState(true);
  const [lang, setLang] = useState<Lang>('cn');
  const [showLabels, setShowLabels] = useState(true);
  const [drillLevel, setDrillLevel] = useState<DrillLevel>('sz');
  const toggleLang = useCallback(() => setLang(l => l === 'cn' ? 'en' : 'cn'), []);

  const findPA = useCallback((paId: string): FGeom => {
    const f = planningAreas?.features.find(x => x.properties?.PLN_AREA_N === paId);
    return f?.geometry ? { type:'Feature', properties:{}, geometry:f.geometry } as FGeom : null;
  }, [planningAreas]);

  const hSelectPA = useCallback((r: SelectedRegion) => {
    if (drillLevel === 'free') { setSelectedArea(r); onSelect?.(r); return; } // select only, no zoom
    setSelectedArea(r); setDrillPA(r.id); setDrillSZ(null);
    const g = findPA(r.id); setFocusGeom(g); setMaskGeom(g);
    try { if (g) { const b = bbox(g); setFocusState({ bounds:[[b[1],b[0]],[b[3],b[2]]], label:r.name }); } } catch { console.warn('hSelectPA bbox failed:', r.name); }
    onSelect?.(r);
  }, [onSelect, setSelectedArea, findPA, drillLevel]);

  const hHoverPA = useCallback((r: SelectedRegion | null) => { setHoveredArea(r); onHover?.(r); }, [onHover, setHoveredArea]);

  const hFocusSZ = useCallback((id: string, f: Feature) => {
    if (drillLevel !== 'sz') return; // subzone drill only at 'sz' level
    setDrillSZ(id); setOsmFeat(null);
    const g = { type:'Feature', properties:{}, geometry:f.geometry } as FGeom; setFocusGeom(g);
    setSelectedArea({ id, name: id, type: 'subzone' });
  }, [setSelectedArea, drillLevel]);

  const hClear = useCallback(() => {
    setDrillPA(null); setDrillSZ(null);
    setFocusGeom(null); setMaskGeom(null); setFocusState(null);
    setOsmFeat(null); setSelectedArea(null);
  }, []);

  const tog = useCallback((id: string) => setActiveCats(p => { const n = new Set(p); n.has(id)?n.delete(id):n.add(id); return n; }), []);
  const togG = useCallback((gid: string, sel: boolean) => {
    const g = OSM_GROUPS.find(x => x.id === gid); if (!g) return;
    setActiveCats(p => { const n = new Set(p); for (const c of g.categories) sel?n.add(c.id):n.delete(c.id); return n; });
  }, []);

  if (error) return <div className="sg-map sg-map--error"><p>Failed to load map data: {error}</p></div>;

  return (
    <div className={`sg-map ${className ?? ''}`}>
      {loading && <div className="sg-map__loading"><div className="sg-map__spinner" /><span>Loading...</span></div>}
      <MapContainer center={SG} zoom={11} minZoom={10} maxZoom={18} zoomSnap={0.25} zoomDelta={0.5} className="sg-map__container">
        <ZoomDebug onZoom={setDebugZoom} />
        <MapLayers
          planningAreas={planningAreas} subzones={subzones} colorMap={colorMap} selectedArea={selectedArea} scoresLoaded={scoresLoaded}
          drillPA={drillPA} drillSZ={drillSZ} focusGeom={focusGeom} maskGeom={maskGeom} focusState={focusState}
          activeCats={activeCats} satellite={satellite} filteredListings={filtered} selectedListingId={selListing?.id ?? null}
          onSelectPA={hSelectPA} onHoverPA={hHoverPA} onFocusSZ={hFocusSZ} onClear={hClear}
          onSelectListing={setSelListing} onSelectOsm={hSelectOsm}
          showHeatmap={showHeatmap} showLabels={showLabels} freeMode={drillLevel === 'free'} />
      </MapContainer>
      <RegionPanel satellite={satellite} showHeatmap={showHeatmap} showLabels={showLabels} drillLevel={drillLevel}
        onToggleSatellite={() => setSatellite(s => !s)} onToggleHeatmap={() => setShowHeatmap(s => !s)} onToggleLabels={() => setShowLabels(s => !s)} onDrillLevel={setDrillLevel} />
      <LayerPanel groups={OSM_GROUPS} active={activeCats} onToggle={tog} onToggleGroup={togG}
        lang={lang} showLabels={showLabels} onToggleLabels={() => setShowLabels(s => !s)} onToggleLang={toggleLang} />
      <RentalDetailPanel listing={selListing} onClose={() => setSelListing(null)} labelMap={listingLabelMap} />
      <OsmDetailPanel feature={osmFeat} categoryLabel={osmLabel} onClose={() => setOsmFeat(null)} />
      {(drillPA || drillSZ) && (
        <div className="drill-banner"><span>{drillSZ ? `📍 ${drillSZ}` : `📍 ${drillPA} — 点击子区深入查看`}</span>
          <button onClick={hClear}>← 返回全岛视图</button></div>
      )}
      <div className="vp-debug">🔍 z{debugZoom}</div>
    </div>
  );
}

export type { SingaporeMapProps, SelectedRegion, RentalListing, ListingLabelMap } from '../../lib/types';
export { findRegionByCoords, buildFeatureIndex, findRegionInIndex } from '../../lib/geo-utils';
export { generateColorMap } from '../../lib/colors';
