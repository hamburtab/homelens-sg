/**
 * Rental listing markers layer.
 *
 * Renders coloured price markers on the map. Each marker is a
 * L.divIcon with the monthly rent displayed inside a rounded pill.
 *
 * Colour bands:
 *   < $2,000   → green
 *   $2k – $4k  → amber
 *   > $4,000   → red
 * Selected marker → larger + purple border
 */

import { useMemo } from 'react';
import { Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import type { RentalListing } from '../../lib/types';

interface RentalMarkersProps {
  listings: RentalListing[];
  selectedId: string | null;
  onSelect: (listing: RentalListing) => void;
}

// ---- Price formatting ----
function fmtPrice(n: number): string {
  if (n >= 1000) return `$${(n / 1000).toFixed(n % 1000 === 0 ? 0 : 1)}K`;
  return `$${n}`;
}

// ---- Colour band ----
type PriceBand = 'cheap' | 'mid' | 'expensive' | 'unknown';

function getBand(price: number | undefined): PriceBand {
  if (price === undefined || price === null) return 'unknown';
  if (price < 2000) return 'cheap';
  if (price <= 4000) return 'mid';
  return 'expensive';
}

const BAND_COLORS: Record<PriceBand, { bg: string; border: string }> = {
  cheap: { bg: '#16a34a', border: '#15803d' },
  mid: { bg: '#d97706', border: '#b45309' },
  expensive: { bg: '#dc2626', border: '#b91c1c' },
  unknown: { bg: '#6366f1', border: '#4f46e5' },
};

// ---- Icon factory ----
function createIcon(price: number | undefined, title: string, isActive: boolean): L.DivIcon {
  const band = getBand(price);
  const colors = BAND_COLORS[band];
  const scale = isActive ? '1.25' : '1';
  const borderColor = isActive ? '#8B5CF6' : colors.border;
  const borderWidth = isActive ? '3px' : '1.5px';
  const label = price !== undefined && price !== null ? fmtPrice(price) : '?';

  return L.divIcon({
    className: 'rental-marker',
    html: `<div class="rental-marker__inner rental-marker__inner--${band}${isActive ? ' rental-marker__inner--active' : ''}"
                style="transform:scale(${scale}); border-color:${borderColor}; border-width:${borderWidth}"
                title="${title}">
             ${label}
           </div>`,
    iconSize: [0, 0],
    iconAnchor: [0, 0],
  });
}

// ---- Component ----
export function RentalMarkers({ listings, selectedId, onSelect }: RentalMarkersProps) {
  // Memoize icons so they don't regenerate on every render
  const icons = useMemo(() => {
    const map = new Map<string, L.DivIcon>();
    for (const l of listings) {
      map.set(l.id, createIcon(l.price, l.title ?? l.id, l.id === selectedId));
    }
    return map;
  }, [listings, selectedId]);

  if (listings.length === 0) return null;

  return (
    <>
      {listings.map((listing) => (
        <Marker
          key={listing.id}
          position={[listing.latitude, listing.longitude]}
          icon={icons.get(listing.id)}
          eventHandlers={{
            click: () => onSelect(listing),
          }}
        >
          <Popup>
            <div className="rental-popup">
              <strong>{listing.title ?? listing.id}</strong>
              <br />
              {listing.price !== undefined && listing.price !== null && (
                <span className="rental-popup__price">{fmtPrice(listing.price)}/mo</span>
              )}
              {listing.bedrooms !== undefined && ` • ${listing.bedrooms} bd`}
              {listing.areaSqft !== undefined && ` • ${listing.areaSqft} sqft`}
            </div>
          </Popup>
        </Marker>
      ))}
    </>
  );
}
