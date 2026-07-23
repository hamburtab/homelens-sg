export interface PlanningAreaProperties { PLN_AREA_N: string; [key: string]: unknown; }
export interface SubzoneProperties { SUBZONE_N: string; PLN_AREA_N: string; [key: string]: unknown; }
export type ViewMode = 'planning' | 'subzone';

export interface SelectedRegion { id: string; name: string; type: ViewMode; parentId?: string; }
export type ColorMap = Map<string, string>;

export interface LayerCategory {
  id: string; label: string; labelEn?: string; icon: string; color: string; dataSource: string;
}
export interface LayerGroup {
  id: string; label: string; labelEn?: string; categories: LayerCategory[];
}
export interface FocusState { bounds: [[number, number], [number, number]]; label: string; }

/** UI language */
export type Lang = 'cn' | 'en';

/**
 * Props for SingaporeMap.
 * Rental data is loaded from `listingsUrl` (JSON array of RentalListing).
 * Use `listingFilter` / `listingSort` for client-side filtering and ordering.
 * Pass `listingLabelMap` to provide human-readable labels for custom fields in the detail panel.
 * Additional scraper fields on RentalListing are rendered automatically via `[key: string]: unknown`.
 */
export interface SingaporeMapProps {
  onSelect?: (region: SelectedRegion) => void;
  onHover?: (region: SelectedRegion | null) => void;
  defaultView?: ViewMode;
  className?: string;
  /** URL to fetch rental listings JSON (omit to hide rentals) */
  listingsUrl?: string;
  /** Client-side filter for rental listings */
  listingFilter?: (listing: RentalListing) => boolean;
  /** Client-side sort for rental listings */
  listingSort?: (a: RentalListing, b: RentalListing) => number;
  /** Maps field names to display labels in the rental detail panel */
  listingLabelMap?: ListingLabelMap;
}

/** Flexible listing interface — scraper can add any extra fields via the index signature. */
export interface RentalListing {
  id: string; latitude: number; longitude: number; title?: string; price?: number;
  address?: string; propertyType?: string; bedrooms?: number; bathrooms?: number;
  areaSqft?: number; areaSqm?: number; furnishing?: string; images?: string[];
  url?: string; description?: string; postedDate?: string; district?: string;
  nearestMRT?: string; amenities?: string[]; [key: string]: unknown;
}
export type ListingLabelMap = Record<string, string>;

export type PlanningAreaCollection = GeoJSON.FeatureCollection<GeoJSON.MultiPolygon | GeoJSON.Polygon, PlanningAreaProperties>;
export type SubzoneCollection = GeoJSON.FeatureCollection<GeoJSON.MultiPolygon | GeoJSON.Polygon, SubzoneProperties>;
