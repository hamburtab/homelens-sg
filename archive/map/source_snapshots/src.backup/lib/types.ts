/**
 * Singapore Map Module — Shared Type Definitions
 *
 * These types model the URA Master Plan 2019 boundary data.
 * PLN_AREA_N is the official primary key for Planning Areas.
 * SUBZONE_N is the official primary key for Subzones.
 */

// ---- GeoJSON Property Types ----

/** Properties attached to each Planning Area feature in planning-areas.geojson */
export interface PlanningAreaProperties {
  PLN_AREA_N: string; // Official unique identifier (e.g. "Bedok", "Jurong West")
  [key: string]: unknown; // Allow extra fields from source data
}

/** Properties attached to each Subzone feature in subzones.geojson */
export interface SubzoneProperties {
  SUBZONE_N: string; // Official unique identifier
  PLN_AREA_N: string; // Parent Planning Area key
  [key: string]: unknown;
}

// ---- View Mode ----

export type ViewMode = 'planning' | 'subzone';

// ---- Selected Region (exposed to parent system) ----

export interface SelectedRegion {
  id: string; // PLN_AREA_N or SUBZONE_N
  name: string; // Human-readable display name
  type: ViewMode;
  parentId?: string; // Parent PLN_AREA_N when type === 'subzone'
}

// ---- Color Map ----

/** Maps a Planning Area key → HSL color string */
export type ColorMap = Map<string, string>;

// ---- Component Props (Public API) ----

export interface SingaporeMapProps {
  /** Called when a user clicks a polygon */
  onSelect?: (region: SelectedRegion) => void;
  /** Called on hover enter/leave; null on leave */
  onHover?: (region: SelectedRegion | null) => void;
  /** Initial view mode; defaults to 'planning' */
  defaultView?: ViewMode;
  /** Additional CSS class for the wrapper */
  className?: string;
}

// ---- Rental Listings ----

/**
 * Rental listing from scraper agent.
 *
 * Only `id`, `latitude`, `longitude` are strictly required.
 * All other fields are optional and will be auto-rendered in the detail panel.
 * Extra fields not defined here pass through via the index signature.
 */
export interface RentalListing {
  id: string;
  latitude: number;
  longitude: number;
  title?: string;
  price?: number;
  address?: string;
  propertyType?: string;
  bedrooms?: number;
  bathrooms?: number;
  areaSqft?: number;
  areaSqm?: number;
  furnishing?: string;
  images?: string[];
  url?: string;
  description?: string;
  postedDate?: string;
  district?: string;
  nearestMRT?: string;
  amenities?: string[];
  [key: string]: unknown; // Allow scraper to add arbitrary fields
}

/**
 * Map scraper field names to human-readable labels for the detail panel.
 * Keys not mentioned here will use the raw field name as fallback.
 */
export type ListingLabelMap = Record<string, string>;

// ---- Component Props (Public API) ----

export interface SingaporeMapProps {
  /** Called when a user clicks a polygon */
  onSelect?: (region: SelectedRegion) => void;
  /** Called on hover enter/leave; null on leave */
  onHover?: (region: SelectedRegion | null) => void;
  /** Initial view mode; defaults to 'planning' */
  defaultView?: ViewMode;
  /** Additional CSS class for the wrapper */
  className?: string;
  /** URL to rental listings JSON; omit to hide listings layer */
  listingsUrl?: string;
  /** Filter function for listings (for recommendation system) */
  listingFilter?: (listing: RentalListing) => boolean;
  /** Sort function for listings (for recommendation system) */
  listingSort?: (a: RentalListing, b: RentalListing) => number;
  /** Map field names → display labels for the detail panel */
  listingLabelMap?: ListingLabelMap;
}

// ---- GeoJSON Feature Collections (raw) ----

export type PlanningAreaCollection = GeoJSON.FeatureCollection<
  GeoJSON.MultiPolygon | GeoJSON.Polygon,
  PlanningAreaProperties
>;

export type SubzoneCollection = GeoJSON.FeatureCollection<
  GeoJSON.MultiPolygon | GeoJSON.Polygon,
  SubzoneProperties
>;
