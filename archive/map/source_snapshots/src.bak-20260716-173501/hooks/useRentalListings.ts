/**
 * Rental listings data hook.
 *
 * Loads listings.json from public/ (or a custom URL).
 * Module-level cache avoids re-fetching on re-mounts.
 */

import { useState, useEffect, useMemo } from 'react';
import type { RentalListing } from '../lib/types';

// ---- Module-level cache ----
let listingsCache: RentalListing[] | null = null;
let cacheUrl: string | null = null;

// ---- Hook ----

interface UseRentalListingsResult {
  listings: RentalListing[];
  loading: boolean;
  error: string | null;
}

export function useRentalListings(
  listingsUrl: string = '/listings.json',
): UseRentalListingsResult {
  const [listings, setListings] = useState<RentalListing[]>(
    cacheUrl === listingsUrl ? listingsCache ?? [] : [],
  );
  const [loading, setLoading] = useState(
    cacheUrl !== listingsUrl || !listingsCache,
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Return cached data if URL matches
    if (cacheUrl === listingsUrl && listingsCache) {
      setListings(listingsCache);
      setLoading(false);
      return;
    }

    let cancelled = false;

    async function fetchListings() {
      try {
        const resp = await fetch(listingsUrl);
        if (!resp.ok) {
          // 404 means no listings — not an error, just empty
          if (resp.status === 404) {
            listingsCache = [];
            cacheUrl = listingsUrl;
            if (!cancelled) {
              setListings([]);
              setLoading(false);
            }
            return;
          }
          throw new Error(`Failed to load listings (HTTP ${resp.status})`);
        }

        const data: RentalListing[] = await resp.json();
        listingsCache = data;
        cacheUrl = listingsUrl;

        if (!cancelled) {
          setListings(data);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : 'Unknown error loading listings',
          );
          setLoading(false);
        }
      }
    }

    fetchListings();
    return () => { cancelled = true; };
  }, [listingsUrl]);

  return { listings, loading, error };
}

/**
 * Convenience: apply filter & sort to listings (for recommendation system).
 * Returns a memoized array so it only re-computes when inputs change.
 */
export function useFilteredListings(
  listings: RentalListing[],
  filter?: (listing: RentalListing) => boolean,
  sort?: (a: RentalListing, b: RentalListing) => number,
): RentalListing[] {
  return useMemo(() => {
    let result = listings;
    if (filter) result = result.filter(filter);
    if (sort) result = [...result].sort(sort);
    return result;
  }, [listings, filter, sort]);
}
