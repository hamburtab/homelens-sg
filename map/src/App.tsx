import { useEffect, useMemo, useState } from 'react';
import type { CSSProperties, FormEvent } from 'react';
import { SingaporeMap } from './components/singapore-map';
import { RedditScorePanel } from './components/singapore-map/RedditScorePanel';
import type { RedditAreaNlp } from './components/singapore-map/RedditScorePanel';
import { AdvisorView } from './components/advisor/AdvisorView';
import type { AdvisorRecommendations } from './components/advisor/AdvisorView';
import type {
  FacilityCounts,
  LocationAnchor,
  RegionProfile,
  RentalListing,
  SelectedRegion,
  SubzoneProfile,
} from './lib/types';
import type { DisplayComment } from './lib/display-comments';
import { parseCommentPool, pickRegionComments } from './lib/display-comments';
import './App.css';

type View = 'explore' | 'advisor' | 'recommend' | 'listings' | 'method';
type ListingMode = 'sale' | 'rent';

interface ProductStatus {
  generatedAt: string;
  historicalMarket: {
    candidateRows: number;
    towns: number;
    rowsWithCoordinates: number;
    latestObservationMonth: string;
  };
  liveListings: {
    sale: { rows: number; coordinate_coverage: number; planning_area_coverage: number };
    rent: { rows: number; coordinate_coverage: number; planning_area_coverage: number };
    latestScrape: string;
    saleParsedPageRanges: string[];
    saleRawPagesAwaitingImport: string;
    knownSalePageGap: string;
    coverageWarning: string;
  };
  communityEvidence: {
    planningAreas: number;
    subzones: number;
    dimensions: string[];
    privacy: string;
  };
  model: { role: string; holdoutMapePercent: number; holdoutR2: number };
  unavailable: string[];
}

interface Health {
  status: string;
  candidate_rows?: number;
  candidate_rows_with_coordinates?: number;
  latest_observation_month?: string;
  towns?: string[];
  integrations?: { openai?: boolean; onemap?: boolean; web_search?: boolean };
  live_listings?: { available: boolean; sale: number; rent: number };
}

interface Recommendation {
  rank: number;
  candidate_id: string;
  town: string;
  block_address: string;
  flat_type: string;
  flat_model: string;
  ranking_score: number;
  score_breakdown: Record<string, number | null>;
  evidence_coverage: number;
  pareto_efficient: boolean;
  preferred_town_match: boolean;
  median_resale_price: number;
  observed_price_low: number;
  observed_price_high: number;
  median_floor_area_sqm: number;
  median_remaining_lease_years: number;
  recent_transaction_count: number;
  evidence_strength: string;
  last_transaction_month: string;
  price_trend_pct_annual?: number | null;
  nearest_mrt_name?: string | null;
  nearest_mrt_distance_m?: number | null;
  amenities_1km?: number | null;
  anchor_distance_m?: number | null;
  ml_reference_price?: number;
  reasons: string[];
}

interface RecommendationResponse {
  recommendations: Recommendation[];
  live_listings: Array<Record<string, unknown>>;
  eligible_candidate_count: number;
  total_candidate_count: number;
  hard_filters: string[];
  warnings: string[];
  near_misses: Array<Record<string, unknown>>;
  intent: { method: string; warnings?: string[] };
  listing_context?: { role?: string };
  model_context?: { available?: boolean; holdout_mape_percent?: number };
  anchor_context?: {
    name?: string;
    latitude: number;
    longitude: number;
    planning_area: string;
    subzone: string;
    distance_type: string;
  } | null;
  disclaimer: string;
}

interface LocationCandidateResponse {
  id: string;
  provider: 'onemap';
  name: string;
  address: string;
  postal_code?: string;
  latitude: number;
  longitude: number;
  confidence: number;
  planning_area: string;
  subzone: string;
}

interface LocationConfirmationResponse {
  status: 'location_confirmation_required';
  location_query: string;
  location_candidates: LocationCandidateResponse[];
  message: string;
}

const DIMENSIONS = [
  ['transport', 'Transit'],
  ['food', 'Food'],
  ['shopping', 'Shopping'],
  ['education', 'Education'],
  ['nature', 'Nature'],
  ['recreation', 'Recreation'],
] as const;

const FACILITY_GROUPS = [
  { label: 'Transit', items: [['MRT stations', 'railwayStations'], ['Bus stops', 'busStops']] },
  { label: 'Food', items: [['Food courts', 'foodCourts'], ['Restaurants', 'restaurants'], ['Cafes', 'cafes']] },
  { label: 'Shopping', items: [['Malls', 'malls'], ['Supermarkets', 'supermarkets'], ['Convenience', 'convenienceStores']] },
  { label: 'Education', items: [['Schools', 'schools'], ['Kindergartens', 'kindergartens']] },
  { label: 'Nature', items: [['Parks', 'parks'], ['Nature reserves', 'natureReserves']] },
  { label: 'Recreation', items: [['Sports centres', 'sportsCentres']] },
] as const;

function facilityValue(counts: FacilityCounts | undefined, key: keyof FacilityCounts) {
  return counts?.[key] ?? 0;
}

function totalFacilities(counts: FacilityCounts | undefined) {
  if (!counts) return 0;
  return Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0);
}

const money = new Intl.NumberFormat('en-SG', {
  style: 'currency',
  currency: 'SGD',
  maximumFractionDigits: 0,
});

const compact = new Intl.NumberFormat('en-SG', { notation: 'compact', maximumFractionDigits: 1 });

function titleCase(value: string) {
  return value.toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value?: string) {
  if (!value) return 'Unknown';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString('en-SG', { day: 'numeric', month: 'short', year: 'numeric' });
}

function listingLocation(listing: RentalListing) {
  return String(listing.subzone || listing.planningArea || listing.town || 'Location unresolved');
}

function listingPrice(listing: RentalListing) {
  if (listing.price == null) return 'Price unavailable';
  return `${money.format(listing.price)}${listing.mode === 'rent' ? ' / month' : ''}`;
}

function distanceMeters(aLat: number, aLng: number, bLat: number, bLng: number) {
  const radians = (degrees: number) => degrees * Math.PI / 180;
  const dLat = radians(bLat - aLat);
  const dLng = radians(bLng - aLng);
  const firstLat = radians(aLat);
  const secondLat = radians(bLat);
  const value = Math.sin(dLat / 2) ** 2
    + Math.cos(firstLat) * Math.cos(secondLat) * Math.sin(dLng / 2) ** 2;
  return 6_371_000 * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value));
}

function ScoreRing({ score, size = 'large' }: { score?: number | null; size?: 'small' | 'large' }) {
  const value = Math.round(score ?? 0);
  return (
    <div
      className={`score-ring score-ring--${size}`}
      style={{ '--score-angle': `${value * 3.6}deg` } as CSSProperties}
      aria-label={score == null ? 'Score unavailable' : `Liveability score ${value} out of 100`}
    >
      <span>{score == null ? '-' : value}</span>
      {size === 'large' && <small>LIVEABILITY</small>}
    </div>
  );
}

function DimensionBars({ profile }: { profile: RegionProfile | SubzoneProfile }) {
  const counts = profile.facilityCounts;
  return (
    <div className="facility-list">
      {FACILITY_GROUPS.map((group) => {
        const total = group.items.reduce(
          (sum, [, key]) => sum + facilityValue(counts, key),
          0,
        );
        return (
          <div className="facility-group" key={group.label}>
            <div className="facility-group__head"><span>{group.label}</span><b>{compact.format(total)}</b></div>
            <div className="facility-group__items">
              {group.items.map(([label, key]) => (
                <span key={key}>{label}<b>{compact.format(facilityValue(counts, key))}</b></span>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function commentExcerpt(comment: DisplayComment) {
  const value = (comment.evidence_span || comment.text || '').trim();
  return value.length > 180 ? `${value.slice(0, 177)}...` : value;
}

function RegionComments({ comments, region, className = '' }: { comments: DisplayComment[]; region: SelectedRegion; className?: string }) {
  const sourceLabel = region.type === 'planning' ? 'Reddit' : 'Google';
  return (
    <section className={`region-comments ${className}`} aria-label={`${sourceLabel} community comments`}>
      <div className="region-comments__head">
        <span>{sourceLabel} comments</span>
      </div>
      {comments.length ? (
        <div className="region-comments__list">
          {comments.map((comment) => {
            const content = commentExcerpt(comment);
            const meta = comment.google_category || comment.aspects?.slice(0, 2).join(' / ') || comment.sentiment || sourceLabel;
            return (
              <article className="region-comment" key={comment.comment_id}>
                <p>&ldquo;{content}&rdquo;</p>
                <footer>
                  <span>{meta}</span>
                  {comment.permalink && <a href={comment.permalink} target="_blank" rel="noreferrer">Source</a>}
                </footer>
              </article>
            );
          })}
        </div>
      ) : (
        <p className="region-comments__empty">No matched {sourceLabel.toLowerCase()} comments are available for this area yet.</p>
      )}
    </section>
  );
}

function App() {
  const [view, setView] = useState<View>('explore');
  const [health, setHealth] = useState<Health | null>(null);
  const [status, setStatus] = useState<ProductStatus | null>(null);
  const [regions, setRegions] = useState<Record<string, RegionProfile>>({});
  const [subzones, setSubzones] = useState<Record<string, SubzoneProfile>>({});
  const [listings, setListings] = useState<RentalListing[]>([]);
  const [dataError, setDataError] = useState('');
  const [selectedRegion, setSelectedRegion] = useState<SelectedRegion | null>(null);
  const [mapListingMode, setMapListingMode] = useState<'none' | ListingMode>('none');
  const [anchorLocation, setAnchorLocation] = useState<LocationAnchor | null>(null);
  const [advisorRecommendations, setAdvisorRecommendations] = useState<AdvisorRecommendations | null>(null);
  const [advisorMapListingIds, setAdvisorMapListingIds] = useState<string[] | null>(null);
  const [commentPool, setCommentPool] = useState<DisplayComment[]>([]);
  const [redditAreaScores, setRedditAreaScores] = useState<RedditAreaNlp | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [regionResponse, subzoneResponse, listingResponse, statusResponse] = await Promise.all([
          fetch('/region-profiles.json'),
          fetch('/subzone-profiles.json'),
          fetch('/live-listings.json'),
          fetch('/data-status.json'),
        ]);
        if (![regionResponse, subzoneResponse, listingResponse, statusResponse].every((response) => response.ok)) {
          throw new Error('One or more product datasets could not be loaded.');
        }
        const [regionData, subzoneData, listingData, statusData] = await Promise.all([
          regionResponse.json(),
          subzoneResponse.json(),
          listingResponse.json(),
          statusResponse.json(),
        ]);
        if (!cancelled) {
          setRegions(regionData.profiles || {});
          setSubzones(subzoneData.profiles || {});
          setListings(listingData || []);
          setStatus(statusData);
        }
      } catch (error) {
        if (!cancelled) setDataError(error instanceof Error ? error.message : 'Data load failed.');
      }
      try {
        const response = await fetch('/api/overview');
        if (response.ok && !cancelled) {
          const overview = await response.json();
          setHealth(overview.health || null);
        }
      } catch {
        if (!cancelled) setHealth(null);
      }
      try {
        const response = await fetch('/display-comment-pool.jsonl');
        if (response.ok && !cancelled) {
          setCommentPool(parseCommentPool(await response.text()));
        }
      } catch {
        if (!cancelled) setCommentPool([]);
      }
      try {
        const response = await fetch('/area_reddit_nlp.json');
        if (response.ok && !cancelled) {
          setRedditAreaScores(await response.json());
        }
      } catch {
        if (!cancelled) setRedditAreaScores(null);
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  const regionScores = useMemo(
    () => Object.fromEntries(
      Object.entries(regions)
        .filter(([, profile]) => profile.liveabilityScore != null)
        .map(([name, profile]) => [name, Number(profile.liveabilityScore)]),
    ),
    [regions],
  );

  const selectedProfile = useMemo(() => {
    if (!selectedRegion) return null;
    return selectedRegion.type === 'planning'
      ? regions[selectedRegion.id]
      : subzones[selectedRegion.id];
  }, [selectedRegion, regions, subzones]);

  const selectedComments = useMemo(
    () => pickRegionComments(commentPool, selectedRegion),
    [commentPool, selectedRegion],
  );

  const mapFilter = useMemo(() => {
    const advisorIdSet = advisorMapListingIds ? new Set(advisorMapListingIds) : null;
    return (listing: RentalListing) => {
      if (mapListingMode === 'none' || listing.mode !== mapListingMode) return false;
      if (advisorIdSet && !advisorIdSet.has(listing.id)) return false;
      if (selectedRegion) {
        if (selectedRegion.type === 'planning' && listing.planningArea !== selectedRegion.id) return false;
        if (selectedRegion.type === 'subzone' && listing.subzone !== selectedRegion.id) return false;
      }
      if (anchorLocation?.maxDistanceM) {
        if (!Number.isFinite(listing.latitude) || !Number.isFinite(listing.longitude)) return false;
        return distanceMeters(
          anchorLocation.latitude,
          anchorLocation.longitude,
          Number(listing.latitude),
          Number(listing.longitude),
        ) <= anchorLocation.maxDistanceM;
      }
      return true;
    };
  }, [advisorMapListingIds, anchorLocation, mapListingMode, selectedRegion]);

  const chooseAreaForSearch = () => {
    setView('recommend');
    window.setTimeout(() => {
      document.querySelector('#recommendation')?.scrollIntoView({ behavior: 'smooth' });
    }, 0);
  };

  return (
    <div className="app-shell">
      <header className="site-header">
        <button className="brand" onClick={() => setView('explore')} aria-label="SG HomeRadar home">
          <span className="brand-beacon"><i /></span>
          <span><strong>SG HomeRadar</strong><small>Evidence for a better move</small></span>
        </button>
        <nav aria-label="Primary navigation">
          {([
            ['explore', 'Explore'],
            ['advisor', 'AI advisor'],
            ['recommend', 'Find a home'],
            ['listings', 'Live listings'],
            ['method', 'How it works'],
          ] as Array<[View, string]>).map(([id, label]) => (
            <button key={id} className={view === id ? 'active' : ''} onClick={() => setView(id)}>{label}</button>
          ))}
        </nav>
        <div className={`system-pill ${health?.status === 'ready' ? 'ready' : ''}`}>
          <i /> {health?.status === 'ready' ? 'Knowledge base ready' : 'Local data mode'}
        </div>
      </header>

      {dataError && <div className="global-alert">{dataError}</div>}

      <main>
        {view === 'explore' && (
          <ExploreView
            status={status}
            regions={regions}
            selectedRegion={selectedRegion}
            selectedProfile={selectedProfile}
            selectedComments={selectedComments}
            redditAreaScores={redditAreaScores}
            setSelectedRegion={setSelectedRegion}
            mapListingMode={mapListingMode}
            setMapListingMode={setMapListingMode}
            advisorMapListingIds={advisorMapListingIds}
            clearAdvisorMapListings={() => setAdvisorMapListingIds(null)}
            regionScores={regionScores}
            subzones={subzones}
            mapFilter={mapFilter}
            chooseAreaForSearch={chooseAreaForSearch}
            goRecommend={() => setView('recommend')}
            goAdvisor={() => setView('advisor')}
            anchorLocation={anchorLocation}
          />
        )}
        {view === 'advisor' && (
          <AdvisorView
            available={Boolean(health?.integrations?.openai)}
            onAnchorChange={setAnchorLocation}
            recommendations={advisorRecommendations}
            onRecommendationsChange={setAdvisorRecommendations}
            onShowMap={(mode, listingIds) => {
              setMapListingMode(mode);
              setAdvisorMapListingIds(listingIds?.length ? listingIds : null);
              setSelectedRegion(null);
              setView('explore');
            }}
          />
        )}
        {view === 'recommend' && (
          <RecommendationView
            health={health}
            initialArea={selectedRegion?.type === 'planning' ? selectedRegion.id : selectedRegion?.parentId}
            anchorLocation={anchorLocation}
            setAnchorLocation={setAnchorLocation}
            onShowMap={() => { setMapListingMode('sale'); setSelectedRegion(null); setView('explore'); }}
          />
        )}
        {view === 'listings' && <ListingsView listings={listings} status={status} />}
        {view === 'method' && <MethodView status={status} />}
      </main>

      <footer className="site-footer">
        <div><strong>SG HomeRadar</strong><span>NUS SWS3023 - Group 3</span></div>
        <p>Decision support from official transactions, partial market listings and aggregate neighbourhood evidence. Not a valuation or financial advice.</p>
      </footer>
    </div>
  );
}

function ExploreView({
  status,
  regions,
  selectedRegion,
  selectedProfile,
  selectedComments,
  redditAreaScores,
  setSelectedRegion,
  mapListingMode,
  setMapListingMode,
  advisorMapListingIds,
  clearAdvisorMapListings,
  regionScores,
  subzones,
  mapFilter,
  chooseAreaForSearch,
  goRecommend,
  goAdvisor,
  anchorLocation,
}: {
  status: ProductStatus | null;
  regions: Record<string, RegionProfile>;
  selectedRegion: SelectedRegion | null;
  selectedProfile: RegionProfile | SubzoneProfile | null;
  selectedComments: DisplayComment[];
  redditAreaScores: RedditAreaNlp | null;
  setSelectedRegion: (value: SelectedRegion) => void;
  mapListingMode: 'none' | ListingMode;
  setMapListingMode: (value: 'none' | ListingMode) => void;
  advisorMapListingIds: string[] | null;
  clearAdvisorMapListings: () => void;
  regionScores: Record<string, number>;
  subzones: Record<string, SubzoneProfile>;
  mapFilter: (listing: RentalListing) => boolean;
  chooseAreaForSearch: () => void;
  goRecommend: () => void;
  goAdvisor: () => void;
  anchorLocation: LocationAnchor | null;
}) {
  const profileIsRegion = selectedProfile && 'subzoneCount' in selectedProfile;
  return (
    <>
      <section className="hero-section">
        <div className="hero-copy-block">
          <p className="overline">SINGAPORE HOUSING, SEEN AS A WHOLE</p>
          <h1>Find the neighbourhood<br />that fits <em>your life.</em></h1>
          <p className="hero-lede">Explore liveability across all 55 planning areas, then turn your needs into an explainable HDB shortlist grounded in real market evidence.</p>
          <div className="hero-actions">
            <button className="button button--primary" onClick={goAdvisor}>Talk to your housing advisor <span>&rarr;</span></button>
            <button className="button button--text" onClick={goRecommend}>I already know my filters &rarr;</button>
            <a className="button button--text" href="#explore-map">Explore map &rarr;</a>
          </div>
        </div>
        <div className="hero-proof" aria-label="Data coverage summary">
          <article><b>{status?.communityEvidence.planningAreas ?? 55}</b><span>planning areas</span><small>Complete boundary coverage</small></article>
          <article><b>{compact.format(status?.historicalMarket.candidateRows ?? 7730)}</b><span>HDB candidates</span><small>24-month evidence windows</small></article>
          <article><b>{compact.format((status?.liveListings.sale.rows ?? 6359) + (status?.liveListings.rent.rows ?? 8041))}</b><span>listing records</span><small>Partial research snapshot</small></article>
        </div>
      </section>

      <section className="map-section" id="explore-map">
        <div className="section-intro">
          <div><p className="overline">MACRO EXPLORATION</p><h2>Read Singapore at a glance.</h2></div>
          <p>Colour reflects an aggregate, reviews-backed liveability score. Click a planning area, then a subzone, to inspect the evidence behind it.</p>
        </div>
        <div className="map-workspace">
          <div className="map-canvas">
            <div className="map-stage">
              <SingaporeMap
                onSelect={setSelectedRegion}
                listingsUrl="/live-listings.json"
                listingFilter={mapFilter}
                listingSort={(a, b) => (b.price ?? 0) - (a.price ?? 0)}
                regionScores={regionScores}
                subzoneScores={subzones}
                maxListingMarkers={300}
                anchorLocation={anchorLocation}
                listingLabelMap={{
                  nearestMRT: 'Nearest MRT',
                  listedOn: 'Listed',
                  areaSqft: 'Floor area',
                  planningArea: 'Planning area',
                  subzone: 'Subzone',
                  locationSource: 'Location evidence',
                }}
              />
              <div className="map-mode-control" role="group" aria-label="Map listing overlay">
                <span>Overlay</span>
                {(['none', 'sale', 'rent'] as const).map((mode) => (
                  <button key={mode} className={mapListingMode === mode ? 'active' : ''} onClick={() => { clearAdvisorMapListings(); setMapListingMode(mode); }}>
                    {mode === 'none' ? 'Areas' : mode === 'sale' ? 'For sale' : 'For rent'}
                  </button>
                ))}
              </div>
              {advisorMapListingIds?.length ? (
                <div className="advisor-map-filter">
                  <span>Advisor picks: {advisorMapListingIds.length}</span>
                  <button type="button" onClick={clearAdvisorMapListings}>Show all {mapListingMode === 'sale' ? 'sale' : 'rent'} listings</button>
                </div>
              ) : null}
              <div className="map-legend"><span><i className="legend-low" />Lower</span><b>Area rating</b><span>Higher<i className="legend-high" /></span></div>
              <RedditScorePanel data={redditAreaScores} selectedRegion={selectedRegion} />
            </div>
            {selectedRegion && selectedProfile && (
              <RegionComments comments={selectedComments} region={selectedRegion} className="map-comments" />
            )}
          </div>
          <aside className="region-panel">
            {!selectedRegion || !selectedProfile ? (
              <div className="region-empty">
                <h3>Choose an area</h3>
                <p>Click any planning area to see mapped facilities, HDB market context and available listings.</p>
                <div className="top-areas">
                  {Object.values(regions).sort((a, b) => totalFacilities(b.facilityCounts) - totalFacilities(a.facilityCounts)).slice(0, 4).map((profile) => (
                    <button key={profile.name} onClick={() => setSelectedRegion({ id: profile.name, name: profile.name, type: 'planning' })}>
                      <span>{titleCase(profile.name)}</span><b>{compact.format(totalFacilities(profile.facilityCounts))}</b>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="region-detail">
                <div className="region-detail__top">
                  <div><p className="overline">{selectedRegion.type === 'planning' ? 'PLANNING AREA' : `SUBZONE - ${titleCase(selectedRegion.parentId || '')}`}</p><h3>{titleCase(selectedRegion.name)}</h3></div>
                </div>
                <DimensionBars profile={selectedProfile} />
                {profileIsRegion && (
                  <>
                    <div className="region-facts">
                      <article><small>For sale</small><b>{compact.format((selectedProfile as RegionProfile).liveSaleListings)}</b></article>
                      <article><small>For rent</small><b>{compact.format((selectedProfile as RegionProfile).liveRentalListings)}</b></article>
                      <article><small>Subzones</small><b>{(selectedProfile as RegionProfile).subzoneCount}</b></article>
                    </div>
                    {(selectedProfile as RegionProfile).market ? (
                      <div className="market-note">
                        <span>Typical recent HDB resale</span>
                        <strong>{money.format((selectedProfile as RegionProfile).market!.medianHdbPrice)}</strong>
                        <small>{compact.format((selectedProfile as RegionProfile).market!.recentTransactions)} recent transactions - through {(selectedProfile as RegionProfile).market!.latestTransactionMonth}</small>
                      </div>
                    ) : <div className="market-note market-note--empty">Historical HDB comparison is not available for this planning area.</div>}
                  </>
                )}
                <button className="button button--primary button--wide" onClick={chooseAreaForSearch}>Find HDB options near here <span>&rarr;</span></button>
                <p className="evidence-footnote">Facility counts are mapped from public GeoJSON layers within each area; review-derived scores remain available only as background evidence.</p>
              </div>
            )}
          </aside>
        </div>
      </section>
    </>
  );
}

function RecommendationView({
  health,
  initialArea,
  anchorLocation,
  setAnchorLocation,
  onShowMap,
}: {
  health: Health | null;
  initialArea?: string;
  anchorLocation: LocationAnchor | null;
  setAnchorLocation: (value: LocationAnchor | null) => void;
  onShowMap: () => void;
}) {
  const [query, setQuery] = useState('A spacious 4-room flat under 650k, within 3 km of NUS and close to MRT.');
  const [budget, setBudget] = useState('650000');
  const [flatType, setFlatType] = useState('4 ROOM');
  const [preferredTown, setPreferredTown] = useState(initialArea || '');
  const [topK, setTopK] = useState('8');
  const [useLlm, setUseLlm] = useState(false);
  const [locationQuery, setLocationQuery] = useState('');
  const [maxDistanceKm, setMaxDistanceKm] = useState('3');
  const [locationCandidates, setLocationCandidates] = useState<LocationCandidateResponse[]>([]);
  const [locationLoading, setLocationLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<RecommendationResponse | null>(null);
  const [compare, setCompare] = useState<string[]>([]);

  useEffect(() => {
    if (initialArea) setPreferredTown(initialArea);
  }, [initialArea]);

  async function searchLocations(searchText = locationQuery): Promise<boolean> {
    const cleaned = searchText.trim();
    if (cleaned.length < 2) {
      setError('Enter at least two characters, such as "NUS" or "VivoCity"');
      return false;
    }
    setError('');
    setLocationLoading(true);
    try {
      const response = await fetch(`/api/locations/search?q=${encodeURIComponent(cleaned)}&limit=5`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || 'OneMap location search is unavailable.');
      setLocationQuery(cleaned);
      setLocationCandidates(data.candidates || []);
      if (!data.candidates?.length) setError(`OneMap found no Singapore location for "${cleaned}". Try a fuller name or address.`);
      return Boolean(data.candidates?.length);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'OneMap location search failed.');
      return false;
    } finally {
      setLocationLoading(false);
    }
  }

  function chooseLocation(candidate: LocationCandidateResponse) {
    setAnchorLocation({
      id: candidate.id,
      provider: 'onemap',
      name: candidate.name,
      address: candidate.address,
      postalCode: candidate.postal_code,
      latitude: candidate.latitude,
      longitude: candidate.longitude,
      confidence: candidate.confidence,
      planningArea: candidate.planning_area,
      subzone: candidate.subzone,
      maxDistanceM: maxDistanceKm ? Number(maxDistanceKm) * 1000 : undefined,
    });
    setLocationQuery(candidate.name);
    setLocationCandidates([]);
    setError('');
    setResult(null);
  }

  function updateMaxDistance(value: string) {
    setMaxDistanceKm(value);
    if (anchorLocation) {
      setAnchorLocation({
        ...anchorLocation,
        maxDistanceM: value ? Number(value) * 1000 : undefined,
      });
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError('');
    if (!query.trim() && !budget.trim()) {
      setError('Add a budget in the brief or the budget field before searching.');
      return;
    }
    if (locationQuery.trim() && !anchorLocation) {
      if (await searchLocations()) {
        setError('Choose the intended OneMap result before building the shortlist.');
      }
      return;
    }
    setLoading(true);
    try {
      const payload: Record<string, unknown> = {
        query: query.trim(),
        top_k: Number(topK),
        use_llm: useLlm,
      };
      if (budget) payload.budget = Number(budget);
      if (flatType) payload.flat_types = [flatType];
      if (preferredTown) payload.preferred_towns = [preferredTown.toUpperCase()];
      if (locationQuery) payload.location_query = locationQuery;
      if (anchorLocation) {
        payload.anchor_name = anchorLocation.name;
        payload.anchor_latitude = anchorLocation.latitude;
        payload.anchor_longitude = anchorLocation.longitude;
        if (anchorLocation.maxDistanceM) payload.max_anchor_distance_m = anchorLocation.maxDistanceM;
      }
      const response = await fetch('/api/recommend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || 'The recommendation service could not complete this search.');
      if (data.status === 'location_confirmation_required') {
        const confirmation = data as LocationConfirmationResponse;
        setLocationQuery(confirmation.location_query);
        setLocationCandidates(confirmation.location_candidates || []);
        setResult(null);
        setError(confirmation.location_candidates?.length
          ? 'Choose the intended OneMap result, then run the search again.'
          : `OneMap found no Singapore location for "${confirmation.location_query}"`);
        return;
      }
      setResult(data as RecommendationResponse);
      setCompare([]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Search failed.');
    } finally {
      setLoading(false);
    }
  }

  function toggleCompare(id: string) {
    setCompare((current) => current.includes(id)
      ? current.filter((item) => item !== id)
      : current.length < 3 ? [...current, id] : current);
  }

  const comparison = (result?.recommendations || []).filter((item) => compare.includes(item.candidate_id));
  return (
    <section className="recommend-section" id="recommendation">
      <div className="recommend-heading">
        <div><p className="overline">MICRO RETRIEVAL</p><h1>Tell us what home means to you.</h1></div>
        <p>Natural language becomes explicit constraints. Budget is never relaxed silently, and every result shows the evidence behind its rank.</p>
      </div>
      <div className="recommend-layout">
        <form className="brief-card" onSubmit={submit}>
          <div className="brief-card__heading"><span>01</span><div><h2>Your housing brief</h2><p>Write naturally, then refine the essentials.</p></div></div>
          <label htmlFor="homeBrief">What are you looking for?</label>
          <textarea id="homeBrief" value={query} onChange={(event) => setQuery(event.target.value)} rows={5} placeholder="A 4-room HDB under 650k, ideally in Tampines" />
          <div className="brief-grid">
            <label>Maximum budget<input type="number" min="50000" step="10000" value={budget} onChange={(event) => setBudget(event.target.value)} /></label>
            <label>Flat type<select value={flatType} onChange={(event) => setFlatType(event.target.value)}><option value="">Any HDB type</option>{['2 ROOM','3 ROOM','4 ROOM','5 ROOM','EXECUTIVE'].map((item) => <option key={item}>{item}</option>)}</select></label>
            <label>Preferred town<input id="preferredTown" list="town-options" value={preferredTown} onChange={(event) => setPreferredTown(event.target.value)} /><datalist id="town-options">{(health?.towns || []).map((town) => <option key={town} value={town} />)}</datalist></label>
            <label>Shortlist size<select value={topK} onChange={(event) => setTopK(event.target.value)}><option value="5">Top 5</option><option value="8">Top 8</option><option value="12">Top 12</option></select></label>
          </div>
          <div className="location-search">
            <div className="location-search__heading">
              <span>Location anchor</span>
              <small>Resolved privately by the server through OneMap</small>
            </div>
            <div className="location-search__row">
              <input
                aria-label="Singapore place or address"
                value={locationQuery}
                onChange={(event) => {
                  setLocationQuery(event.target.value);
                  setLocationCandidates([]);
                  if (anchorLocation) setAnchorLocation(null);
                }}
                placeholder="NUS, VivoCity, or a full address"
              />
              <button type="button" onClick={() => searchLocations()} disabled={locationLoading || locationQuery.trim().length < 2}>
                {locationLoading ? 'Finding...' : 'Find'}
              </button>
            </div>
            {locationCandidates.length > 0 && (
              <div className="location-candidates" role="listbox" aria-label="OneMap location matches">
                <p>Select the intended place</p>
                {locationCandidates.map((candidate) => (
                  <button type="button" key={candidate.id} onClick={() => chooseLocation(candidate)}>
                    <span><b>{candidate.name}</b><small>{candidate.address}</small></span>
                    <em>{titleCase(candidate.subzone)} - {titleCase(candidate.planning_area)}</em>
                  </button>
                ))}
              </div>
            )}
            {anchorLocation && (
              <div className="selected-location">
                <span className="selected-location__pin">*</span>
                <div>
                  <b>{anchorLocation.name}</b>
                  <small>{anchorLocation.address}</small>
                  <em>{titleCase(anchorLocation.subzone)} - {titleCase(anchorLocation.planningArea)} - OneMap verified</em>
                </div>
                <button type="button" onClick={onShowMap}>Map</button>
                <button type="button" aria-label="Remove selected location" onClick={() => { setAnchorLocation(null); setLocationQuery(''); setResult(null); }}>x</button>
              </div>
            )}
            <label className="radius-field">
              Maximum straight-line distance
              <span><input type="number" min="0.2" max="30" step="0.5" value={maxDistanceKm} onChange={(event) => updateMaxDistance(event.target.value)} /><i>km</i></span>
            </label>
            <p className="location-search__note">The radius becomes a hard filter after you confirm a place. It is not walking or public-transport time.</p>
          </div>
          <div className="planned-fields" aria-label="Planned route feature">
            <label>Maximum route travel time<input disabled placeholder="Route data required - coming soon" /></label>
          </div>
          <label className={`ai-toggle ${health?.integrations?.openai ? '' : 'disabled'}`}>
            <input type="checkbox" checked={useLlm} disabled={!health?.integrations?.openai} onChange={(event) => setUseLlm(event.target.checked)} />
            <span><b>AI-assisted intent extraction</b><small>{health?.integrations?.openai ? 'Use the configured language model; deterministic filtering still controls the result.' : 'Not configured in this environment; rule parsing remains available.'}</small></span>
          </label>
          {error && <p className="form-error">{error}</p>}
          <button className="button button--primary button--wide" disabled={loading}>{loading ? 'Comparing evidence...' : 'Build my shortlist'}<span>&rarr;</span></button>
          <p className="brief-assurance"><i /> Hard constraints stay hard - Missing evidence stays visible</p>
        </form>

        <div className="recommend-results" aria-live="polite">
          {!result && !loading && (
            <div className="results-welcome">
              <span className="radar-graphic"><i /><i /><i /></span>
              <p className="overline">EXPLAINABLE BY DESIGN</p>
              <h2>A shortlist you can interrogate.</h2>
              <p>Each option combines observed price, space, remaining lease, market activity and available location evidence.</p>
              <div><article><b>Filter</b><span>Budget & needs</span></article><article><b>Rank</b><span>Trade-offs</span></article><article><b>Explain</b><span>Evidence</span></article></div>
            </div>
          )}
          {loading && <div className="results-loading"><span /><h2>Comparing 7,730 candidates</h2><p>Applying hard constraints before scoring trade-offs.</p></div>}
          {result && !loading && (
            <>
              <div className="results-summary">
                <div><p className="overline">YOUR SHORTLIST</p><h2>{result.recommendations.length ? 'Best-fitting HDB options' : 'No exact match'}</h2></div>
                <p><b>{result.eligible_candidate_count.toLocaleString()}</b> eligible of {result.total_candidate_count.toLocaleString()}</p>
              </div>
              {result.anchor_context && (
                <div className="result-anchor">
                  <span>*</span>
                  <p><b>Measured from {result.anchor_context.name || anchorLocation?.name || 'your selected place'}</b><small>{titleCase(result.anchor_context.subzone)} - straight-line distance</small></p>
                  <button type="button" onClick={onShowMap}>View radius on map &rarr;</button>
                </div>
              )}
              {[...(result.intent.warnings || []), ...(result.warnings || [])].map((warning) => <p className="result-warning" key={warning}>{warning}</p>)}
              {!result.recommendations.length ? (
                <div className="no-results"><h3>No silent compromises.</h3><p>No candidate satisfies every hard condition. Adjust a field yourself; HomeRadar will not do it behind your back.</p></div>
              ) : (
                <div className="recommendation-grid">
                  {result.recommendations.map((item) => <RecommendationCard key={item.candidate_id} item={item} compared={compare.includes(item.candidate_id)} compareFull={compare.length >= 3} onCompare={() => toggleCompare(item.candidate_id)} />)}
                </div>
              )}
              {!!result.live_listings?.length && (
                <div className="live-match-strip">
                  <div><p className="overline">CURRENT MARKET CHECK</p><h3>{result.live_listings.length} partial live-sale matches under your budget</h3><span>{result.listing_context?.role}</span></div>
                  <div>{result.live_listings.slice(0, 4).map((listing) => <article key={String(listing.id)}><b>{money.format(Number(listing.price))}</b><span>{String(listing.address)}</span><small>{listing.anchor_distance_m != null ? `${(Number(listing.anchor_distance_m) / 1000).toFixed(2)} km from anchor` : String(listing.town || listing.planning_area || 'Location unresolved')}</small></article>)}</div>
                </div>
              )}
              <p className="result-disclaimer">{result.disclaimer}</p>
            </>
          )}
        </div>
      </div>
      {comparison.length > 0 && <CompareDrawer items={comparison} onClose={() => setCompare([])} />}
    </section>
  );
}

function RecommendationCard({ item, compared, compareFull, onCompare }: { item: Recommendation; compared: boolean; compareFull: boolean; onCompare: () => void }) {
  return (
    <article className="recommendation-card">
      <div className="recommendation-card__top">
        <span className="rank-badge">{String(item.rank).padStart(2, '0')}</span>
        <div><h3>{item.block_address}</h3><p>{titleCase(item.town)} - {item.flat_type} - {item.flat_model}</p></div>
        <ScoreRing score={item.ranking_score * 100} size="small" />
      </div>
      <div className="tag-row">
        {item.preferred_town_match && <span>Preferred area</span>}
        {item.anchor_distance_m != null && <span>{(item.anchor_distance_m / 1000).toFixed(2)} km from place</span>}
        {item.pareto_efficient && <span className="accent">Strong trade-off</span>}
        <span className={item.evidence_strength === 'low' ? 'caution' : ''}>{item.recent_transaction_count} transactions</span>
      </div>
      <div className="recommendation-metrics">
        <article><small>Observed median</small><b>{money.format(item.median_resale_price)}</b></article>
        <article><small>Middle 50%</small><b>{money.format(item.observed_price_low)}-{money.format(item.observed_price_high)}</b></article>
        <article><small>Typical size</small><b>{Math.round(item.median_floor_area_sqm)} sqm</b></article>
        <article><small>Remaining lease</small><b>{item.median_remaining_lease_years.toFixed(1)} yrs</b></article>
        {item.anchor_distance_m != null && <article><small>Anchor distance</small><b>{(item.anchor_distance_m / 1000).toFixed(2)} km</b></article>}
      </div>
      <div className="evidence-line"><span style={{ width: `${item.evidence_coverage * 100}%` }} /></div>
      <p className="reason">{item.reasons[0]}</p>
      <div className="card-actions">
        <button className={compared ? 'selected' : ''} disabled={!compared && compareFull} onClick={onCompare}>{compared ? 'Added to compare' : 'Compare option'}</button>
        <details><summary>Why this ranked</summary><ul>{item.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></details>
      </div>
    </article>
  );
}

function CompareDrawer({ items, onClose }: { items: Recommendation[]; onClose: () => void }) {
  const rows: Array<[string, (item: Recommendation) => string]> = [
    ['Fit score', (item) => `${Math.round(item.ranking_score * 100)}/100`],
    ['Observed median', (item) => money.format(item.median_resale_price)],
    ['Budget reference', (item) => money.format(item.observed_price_high)],
    ['Typical area', (item) => `${Math.round(item.median_floor_area_sqm)} sqm`],
    ['Remaining lease', (item) => `${item.median_remaining_lease_years.toFixed(1)} years`],
    ['Evidence', (item) => `${item.recent_transaction_count} transactions`],
    ['Anchor distance', (item) => item.anchor_distance_m == null ? 'Not set' : `${(item.anchor_distance_m / 1000).toFixed(2)} km`],
  ];
  return (
    <div className="compare-drawer" role="dialog" aria-label="Compare shortlisted homes">
      <div className="compare-drawer__head"><div><p className="overline">SIDE-BY-SIDE</p><h2>Compare {items.length} option{items.length > 1 ? 's' : ''}</h2></div><button onClick={onClose}>Close x</button></div>
      <div className="compare-table">
        <div className="compare-row compare-row--head"><b>Evidence</b>{items.map((item) => <strong key={item.candidate_id}>{item.block_address}<small>{titleCase(item.town)} - {item.flat_type}</small></strong>)}</div>
        {rows.map(([label, value]) => <div className="compare-row" key={label}><b>{label}</b>{items.map((item) => <span key={item.candidate_id}>{value(item)}</span>)}</div>)}
      </div>
    </div>
  );
}

function ListingsView({ listings, status }: { listings: RentalListing[]; status: ProductStatus | null }) {
  const [mode, setMode] = useState<ListingMode>('sale');
  const [search, setSearch] = useState('');
  const [area, setArea] = useState('');
  const [bedrooms, setBedrooms] = useState('');
  const [maxPrice, setMaxPrice] = useState('');
  const [locatedOnly, setLocatedOnly] = useState(false);
  const [visible, setVisible] = useState(36);

  useEffect(() => { setVisible(36); setMaxPrice(''); }, [mode]);
  const areas = useMemo(() => Array.from(new Set(listings.map((item) => String(item.planningArea || '')).filter(Boolean))).sort(), [listings]);
  const filtered = useMemo(() => {
    const needle = search.trim().toUpperCase();
    return listings.filter((item) => {
      if (item.mode !== mode) return false;
      if (needle && !`${item.title || ''} ${item.address || ''} ${item.planningArea || ''} ${item.subzone || ''}`.toUpperCase().includes(needle)) return false;
      if (area && item.planningArea !== area) return false;
      if (bedrooms && Number(item.bedrooms) !== Number(bedrooms)) return false;
      if (maxPrice && Number(item.price || Infinity) > Number(maxPrice)) return false;
      if (locatedOnly && !(Number.isFinite(item.latitude) && Number.isFinite(item.longitude))) return false;
      return true;
    }).sort((a, b) => String(b.scrapedAt || '').localeCompare(String(a.scrapedAt || '')));
  }, [listings, mode, search, area, bedrooms, maxPrice, locatedOnly]);

  const coverage = mode === 'sale' ? status?.liveListings.sale.coordinate_coverage : status?.liveListings.rent.coordinate_coverage;
  const areaCoverage = mode === 'sale' ? status?.liveListings.sale.planning_area_coverage : status?.liveListings.rent.planning_area_coverage;
  return (
    <section className="listings-section">
      <div className="listings-heading">
        <div><p className="overline">PERIODIC MARKET SNAPSHOT</p><h1>See what is available now.</h1><p>Browse the latest contributed PropertyGuru research extract. Coordinate gaps do not hide a listing from this catalogue.</p></div>
        <div className="snapshot-note"><span>Last collected</span><b>{formatDate(status?.liveListings.latestScrape)}</b><small>{status?.liveListings.coverageWarning}</small></div>
      </div>
      <div className="listing-mode-tabs">
        <button className={mode === 'sale' ? 'active' : ''} onClick={() => setMode('sale')}><span>Buy</span><b>{(status?.liveListings.sale.rows ?? 0).toLocaleString()}</b></button>
        <button className={mode === 'rent' ? 'active' : ''} onClick={() => setMode('rent')}><span>Rent</span><b>{(status?.liveListings.rent.rows ?? 0).toLocaleString()}</b></button>
      </div>
      <div className="listing-filter-bar">
        <label className="search-field"><span>Search</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Address, area or subzone" /></label>
        <label><span>Planning area</span><select value={area} onChange={(event) => setArea(event.target.value)}><option value="">All areas</option>{areas.map((item) => <option key={item}>{item}</option>)}</select></label>
        <label><span>Bedrooms</span><select value={bedrooms} onChange={(event) => setBedrooms(event.target.value)}><option value="">Any</option>{[1,2,3,4,5].map((item) => <option key={item}>{item}</option>)}</select></label>
        <label><span>Maximum {mode === 'rent' ? 'monthly rent' : 'price'}</span><input type="number" value={maxPrice} onChange={(event) => setMaxPrice(event.target.value)} placeholder={mode === 'rent' ? '4000' : '800000'} /></label>
        <label className="located-toggle"><input type="checkbox" checked={locatedOnly} onChange={(event) => setLocatedOnly(event.target.checked)} /><span>Map-located only</span></label>
      </div>
      <div className="listing-results-head"><p><b>{filtered.length.toLocaleString()}</b> matching listings</p><span>{coverage == null ? 'Location coverage unavailable' : `${Math.round((areaCoverage ?? coverage) * 100)}% area-classified - ${Math.round(coverage * 100)}% map-located`}</span></div>
      <div className="listing-grid">
        {filtered.slice(0, visible).map((listing) => <ListingCard key={listing.id} listing={listing} />)}
      </div>
      {!filtered.length && <div className="listing-empty"><h3>No listing matches these filters.</h3><p>Clear one or more filters to widen the catalogue.</p></div>}
      {visible < filtered.length && <button className="button button--secondary load-more" onClick={() => setVisible((count) => count + 36)}>Show more listings</button>}
      {mode === 'sale' && <p className="coverage-banner"><b>Coverage note.</b> Parsed pages: {status?.liveListings.saleParsedPageRanges.join(', ')}. Raw pages {status?.liveListings.saleRawPagesAwaitingImport} await import; known gap: {status?.liveListings.knownSalePageGap}.</p>}
    </section>
  );
}

function ListingCard({ listing }: { listing: RentalListing }) {
  const located = Number.isFinite(listing.latitude) && Number.isFinite(listing.longitude);
  return (
    <article className="listing-card">
      <div className={`listing-card__visual listing-card__visual--${listing.mode}`}>
        <span>{listing.mode === 'sale' ? 'FOR SALE' : 'FOR RENT'}</span>
        <b>{listing.bedrooms ? `${listing.bedrooms} BR` : String(listing.roomType || 'HDB')}</b>
        <i>{located ? 'Map located' : 'Address only'}</i>
      </div>
      <div className="listing-card__body">
        <p className="listing-price">{listingPrice(listing)}</p>
        <h3>{listing.address || listing.title}</h3>
        <span className="listing-location">{titleCase(listingLocation(listing))}</span>
        <div className="listing-specs">
          {listing.areaSqft && <span>{Number(listing.areaSqft).toLocaleString()} sqft</span>}
          {listing.bathrooms && <span>{listing.bathrooms} bath</span>}
          {listing.nearestMRT && <span>{String(listing.nearestMRT).replace(/ MRT Station/i, '')}</span>}
        </div>
        <footer>
          <span>{String(listing.listedOn || 'Collection date only')}</span>
          <small>{located
            ? `Map: ${String(listing.locationSource || 'listing coordinate').replaceAll('_', ' ')}`
            : listing.areaSource
              ? `Area: ${String(listing.areaSource).replaceAll('_', ' ')} - map unresolved`
              : 'Location unresolved'}</small>
        </footer>
      </div>
    </article>
  );
}

function MethodView({ status }: { status: ProductStatus | null }) {
  return (
    <section className="method-section">
      <div className="method-hero"><p className="overline">TRANSPARENT FROM SOURCE TO SCORE</p><h1>Built to show its work.</h1><p>HomeRadar follows CRISP-DM: understand the housing decision, inspect and prepare multiple web and official sources, model price evidence, and evaluate every output with explicit limitations.</p></div>
      <div className="pipeline">
        {[
          ['01', 'Understand', 'Turn housing needs into hard constraints and weighted preferences.'],
          ['02', 'Collect', 'Combine official HDB transactions, periodic listings, facilities and aggregate community evidence.'],
          ['03', 'Prepare', 'Clean values, deduplicate listing IDs, reconcile addresses and preserve missing evidence.'],
          ['04', 'Model', 'Rank trade-offs deterministically; add a time-tested random forest price reference.'],
          ['05', 'Evaluate', 'Check holdout error, filter stability, evidence coverage and data-quality flags.'],
        ].map(([number, title, copy]) => <article key={number}><span>{number}</span><h2>{title}</h2><p>{copy}</p></article>)}
      </div>
      <div className="method-grid">
        <article className="method-card method-card--dark"><p className="overline">PRICE MODEL</p><h2>Reference, never verdict.</h2><div className="model-numbers"><span><b>{status?.model.holdoutMapePercent ?? 5.9}%</b><small>holdout MAPE</small></span><span><b>{status?.model.holdoutR2 ?? 0.928}</b><small>holdout R2</small></span></div><p>A chronological test protects against training on the future. The prediction never overrides observed prices or budget filters.</p></article>
        <article className="method-card"><p className="overline">LIVEABILITY EVIDENCE</p><h2>Six dimensions, 332 subzones.</h2><div className="dimension-pills">{DIMENSIONS.map(([, label]) => <span key={label}>{label}</span>)}</div><p>Only aggregate place counts, ratings and review-derived signals reach the product. Raw review text and author data remain outside the public surface.</p></article>
      </div>
      <div className="availability-section"><div><p className="overline">CAPABILITY BOUNDARY</p><h2>What is ready and what is deliberately not faked.</h2></div><div className="availability-list"><article className="ready"><i />Explainable HDB recommendation<span>Available</span></article><article className="ready"><i />55-area and 332-subzone exploration<span>Available</span></article><article className="ready"><i />OneMap place search and distance radius<span>Available</span></article><article className="ready"><i />Partial sale and rental catalogue<span>Available</span></article>{(status?.unavailable || []).map((item) => <article key={item}><i />{item}<span>Planned</span></article>)}</div></div>
      <div className="source-note"><h3>Data is evidence, not certainty.</h3><p>Listings can be removed or reordered after collection; community ratings reflect the contributed extract; straight-line distances are not walking routes. These limits stay visible instead of being converted into false precision.</p></div>
    </section>
  );
}

export default App;
