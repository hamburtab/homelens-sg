/**
 * Rental listings loading hook with module-level cache.
 * Deferred 500ms to avoid competing with critical GeoJSON on first load.
 */
import { useState, useEffect, useMemo } from 'react';
import type { RentalListing } from '../lib/types';

let listingsCache: RentalListing[] | null = null;
let cacheUrl: string | null = null;

interface UseRentalListingsResult {
  listings: RentalListing[];
  loading: boolean;
  error: string | null;
}

export function useRentalListings(listingsUrl?: string): UseRentalListingsResult {
  const url = listingsUrl ?? '/listings.json';
  const [listings, setListings] = useState<RentalListing[]>(listingsCache ?? []);
  const [loading, setLoading] = useState(!listingsCache);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (listingsCache && cacheUrl === url) {
      setLoading(false);
      return;
    }

    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const resp = await fetch(url);
        if (!resp.ok) {
          if (resp.status === 404) {
            listingsCache = [];
            cacheUrl = url;
            if (!cancelled) { setListings([]); setLoading(false); }
            return;
          }
          throw new Error(`Listings HTTP ${resp.status}`);
        }
        const data: RentalListing[] = await resp.json();
        listingsCache = data;
        cacheUrl = url;
        if (!cancelled) { setListings(data); setLoading(false); }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unknown error');
          setLoading(false);
        }
      }
    }, listingsCache ? 0 : 500); // 500ms defer on first load

    return () => { cancelled = true; clearTimeout(timer); };
  }, [url]);

  return { listings, loading, error };
}

export function useFilteredListings(
  listings: RentalListing[],
  filter?: (l: RentalListing) => boolean,
  sort?: (a: RentalListing, b: RentalListing) => number,
): RentalListing[] {
  return useMemo(() => {
    let result = listings;
    if (filter) result = result.filter(filter);
    if (sort) result = [...result].sort(sort);
    return result;
  }, [listings, filter, sort]);
}
