export interface PlanningAreaProperties { PLN_AREA_N: string; [key: string]: unknown; }
export interface SubzoneProperties { SUBZONE_N: string; PLN_AREA_N: string; [key: string]: unknown; }
export type ViewMode = 'planning' | 'subzone';

export interface SelectedRegion { id: string; name: string; type: ViewMode; parentId?: string; }
export type ColorMap = Map<string, string>;

export interface LayerCategory { id: string; label: string; icon: string; color: string; dataSource: string; }
export interface LayerGroup { id: string; label: string; categories: LayerCategory[]; }
export interface FocusState { bounds: [[number, number], [number, number]]; label: string; }

export interface LocationAnchor {
  id: string;
  provider: 'onemap';
  name: string;
  address: string;
  postalCode?: string;
  latitude: number;
  longitude: number;
  confidence: number;
  planningArea: string;
  subzone: string;
  maxDistanceM?: number;
}

export interface SingaporeMapProps {
  onSelect?: (region: SelectedRegion) => void;
  onHover?: (region: SelectedRegion | null) => void;
  defaultView?: ViewMode;
  className?: string;
  listingsUrl?: string;
  listingFilter?: (listing: RentalListing) => boolean;
  listingSort?: (a: RentalListing, b: RentalListing) => number;
  listingLabelMap?: ListingLabelMap;
  regionScores?: Record<string, number>;
  subzoneScores?: Record<string, SubzoneProfile>;
  maxListingMarkers?: number;
  anchorLocation?: LocationAnchor | null;
}

export interface RentalListing {
  id: string; latitude?: number; longitude?: number; title?: string; price?: number;
  mode?: 'sale' | 'rent';
  address?: string; propertyType?: string; bedrooms?: number; bathrooms?: number;
  areaSqft?: number; areaSqm?: number; furnishing?: string; images?: string[];
  url?: string; description?: string; postedDate?: string; district?: string;
  nearestMRT?: string; amenities?: string[]; [key: string]: unknown;
}
export type ListingLabelMap = Record<string, string>;

export interface DimensionProfile { score: number | null; places: number; reviews: number; }
export interface FacilityCounts {
  railwayStations: number;
  busStops: number;
  malls: number;
  supermarkets: number;
  convenienceStores: number;
  foodCourts: number;
  restaurants: number;
  cafes: number;
  parks: number;
  natureReserves: number;
  sportsCentres: number;
  schools: number;
  kindergartens: number;
}
export interface SubzoneProfile {
  name: string;
  planningArea: string;
  liveabilityScore: number | null;
  dimensions: Record<string, DimensionProfile>;
  facilityCounts?: FacilityCounts;
}

export interface RegionProfile {
  name: string;
  liveabilityScore: number | null;
  dimensions: Record<string, DimensionProfile>;
  facilityCounts?: FacilityCounts;
  subzoneCount: number;
  placeEvidence: number;
  reviewEvidence: number;
  liveSaleListings: number;
  liveRentalListings: number;
  market?: {
    medianHdbPrice: number;
    medianFloorAreaSqm: number;
    candidateCount: number;
    recentTransactions: number;
    latestTransactionMonth: string;
  } | null;
}

export type PlanningAreaCollection = GeoJSON.FeatureCollection<GeoJSON.MultiPolygon | GeoJSON.Polygon, PlanningAreaProperties>;
export type SubzoneCollection = GeoJSON.FeatureCollection<GeoJSON.MultiPolygon | GeoJSON.Polygon, SubzoneProperties>;
