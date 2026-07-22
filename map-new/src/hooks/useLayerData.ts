import { useRef, useCallback, useState } from 'react';
import type { FeatureCollection } from 'geojson';
const cache = new Map<string, FeatureCollection>();
export function useLayerData() {
  const cacheRef = useRef(cache);
  const [loading, setLoading] = useState<Set<string>>(new Set());
  const load = useCallback(async (url: string): Promise<FeatureCollection | null> => {
    if (cache.has(url)) return cache.get(url)!;
    setLoading(p => new Set(p).add(url));
    try {
      const base = import.meta.env.BASE_URL;
      const r = await fetch(`${base}geojson/${url}`);
      if (!r.ok) return null;
      const d: FeatureCollection = await r.json();
      cache.set(url, d);
      return d;
    } finally {
      setLoading(p => { const n = new Set(p); n.delete(url); return n; });
    }
  }, []);
  return { loading, load, cacheRef };
}
