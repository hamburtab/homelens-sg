export interface PlanningAreaProperties { PLN_AREA_N: string; [key: string]: unknown; }
export interface SubzoneProperties { SUBZONE_N: string; PLN_AREA_N: string; [key: string]: unknown; }
export type ViewMode = 'planning' | 'subzone';

export interface SelectedRegion { id: string; name: string; type: ViewMode; parentId?: string; }
export type ColorMap = Map<string, string>;

export interface LayerCategory { id: string; label: string; icon: string; color: string; dataSource: string; }
export interface LayerGroup { id: string; label: string; categories: LayerCategory[]; }
export interface FocusState { bounds: [[number, number], [number, number]]; label: string; }

export interface SingaporeMapProps {
  onSelect?: (region: SelectedRegion) => void;
  onHover?: (region: SelectedRegion | null) => void;
  defaultView?: ViewMode;
  className?: string;
  listingsUrl?: string;
  listingFilter?: (listing: RentalListing) => boolean;
  listingSort?: (a: RentalListing, b: RentalListing) => number;
  listingLabelMap?: ListingLabelMap;
}

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
