/**
 * Right-side slide-in panel showing rental listing details.
 *
 * Adaptive: auto-renders ALL fields from the listing object.
 * - Known fields (title, price, images, etc.) get special formatting.
 * - Unknown fields are rendered as key-value rows using `labelMap` for display names.
 * - If `labelMap` doesn't cover a field, the raw key name is used as fallback.
 */

import type { RentalListing, ListingLabelMap } from '../../lib/types';

interface RentalDetailPanelProps {
  listing: RentalListing | null;
  onClose: () => void;
  labelMap?: ListingLabelMap;
}

// ---- Field role detection (for special rendering) ----
const KNOWN_ROLES: Record<string, 'image' | 'price' | 'title' | 'address' | 'link' | 'meta' | 'tags' | 'skip'> = {
  images: 'image',
  price: 'price',
  title: 'title',
  address: 'address',
  url: 'link',
  bedrooms: 'meta',
  bathrooms: 'meta',
  areaSqft: 'meta',
  areaSqm: 'meta',
  propertyType: 'meta',
  amenities: 'tags',
  id: 'skip',
  latitude: 'skip',
  longitude: 'skip',
};

// ---- Helpers ----
function fmtPrice(n: number): string {
  return `$${n.toLocaleString('en-SG')}`;
}

function fmtValue(value: unknown): string {
  if (typeof value === 'number') return value.toLocaleString('en-SG');
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (value instanceof Date) return value.toLocaleDateString('en-SG');
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}/.test(value)) {
    return new Date(value).toLocaleDateString('en-SG');
  }
  return String(value ?? '—');
}

function labelFor(key: string, labelMap?: ListingLabelMap): string {
  if (labelMap?.[key]) return labelMap[key];
  // Auto-generate readable label from camelCase/snake_case keys
  return key
    .replace(/([A-Z])/g, ' $1')
    .replace(/_/g, ' ')
    .replace(/^./, (c) => c.toUpperCase())
    .trim();
}

// ---- Component ----
export function RentalDetailPanel({ listing, onClose, labelMap }: RentalDetailPanelProps) {
  if (!listing) return null;

  const keys = Object.keys(listing).filter((k) => KNOWN_ROLES[k] !== 'skip');

  // Extract special fields
  const title = listing.title ?? listing.address ?? 'Listing';
  const price = listing.price;
  const address = listing.address;
  const images = listing.images as string[] | undefined;
  const url = listing.url;
  const amenities = listing.amenities as string[] | undefined;

  const primaryImage = images && images.length > 0 ? images[0] : null;

  // Meta fields (bedrooms, bathrooms, propertyType, etc.)
  const metaKeys = keys.filter((k) => KNOWN_ROLES[k] === 'meta');
  const infoKeys = keys.filter(
    (k) => !KNOWN_ROLES[k] || KNOWN_ROLES[k] === undefined,
  );

  return (
    <>
      <div className="rental-detail__backdrop" onClick={onClose} />
      <div className="rental-detail" role="dialog" aria-label="Rental listing details">
        <button className="rental-detail__close" onClick={onClose} aria-label="Close">
          ✕
        </button>

        {/* Image */}
        <div className="rental-detail__image-wrap">
          {primaryImage ? (
            <img className="rental-detail__image" src={primaryImage} alt={title} loading="lazy" />
          ) : (
            <div className="rental-detail__image rental-detail__image--empty" aria-label="No listing image available">No image supplied</div>
          )}
          {images && images.length > 1 && (
            <span className="rental-detail__image-count">1 / {images.length}</span>
          )}
        </div>

        <div className="rental-detail__body">
          {/* Price */}
          {price !== undefined && price !== null && (
            <div className="rental-detail__header">
              <span className="rental-detail__price">{fmtPrice(price)}</span>
              {listing.mode === 'rent' && <span className="rental-detail__per">/mo</span>}
            </div>
          )}

          {/* Title */}
          <h3 className="rental-detail__title">{title}</h3>

          {/* Address */}
          {address && <p className="rental-detail__address">{address}</p>}

          {/* Meta row — bedrooms, bathrooms, area, propertyType */}
          {metaKeys.length > 0 && (
            <div className="rental-detail__meta">
              {metaKeys.map((k) => (
                <div key={k} className="rental-detail__meta-item">
                  <span className="rental-detail__meta-label">{labelFor(k, labelMap)}</span>
                  <span className="rental-detail__meta-value">{fmtValue(listing[k])}</span>
                </div>
              ))}
            </div>
          )}

          {/* Info rows — everything else the scraper sent */}
          {infoKeys.length > 0 && (
            <div className="rental-detail__info">
              {infoKeys.map((k) => (
                <div key={k} className="rental-detail__info-row">
                  <span>{labelFor(k, labelMap)}</span>
                  <span>{fmtValue(listing[k])}</span>
                </div>
              ))}
            </div>
          )}

          {/* Amenities tags */}
          {amenities && amenities.length > 0 && (
            <div className="rental-detail__amenities">
              {amenities.map((a) => (
                <span key={a} className="rental-detail__amenity-tag">{a}</span>
              ))}
            </div>
          )}

          {/* Description */}
          {listing.description && (
            <p className="rental-detail__desc">{listing.description}</p>
          )}

          {/* External link */}
          {url && (
            <a className="rental-detail__link" href={url} target="_blank" rel="noopener noreferrer">
              View Original Listing ↗
            </a>
          )}
        </div>
      </div>
    </>
  );
}
