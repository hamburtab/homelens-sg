import { useEffect } from 'react';
import { latLng } from 'leaflet';
import { Circle, CircleMarker, Popup, useMap } from 'react-leaflet';
import type { LocationAnchor } from '../../lib/types';

export function AnchorLocationLayer({ anchor }: { anchor?: LocationAnchor | null }) {
  const map = useMap();

  useEffect(() => {
    if (!anchor) return;
    if (anchor.maxDistanceM) {
      map.fitBounds(
        latLng(anchor.latitude, anchor.longitude).toBounds(anchor.maxDistanceM * 2),
        { animate: true, duration: 0.7, padding: [35, 35], maxZoom: 15 },
      );
      return;
    }
    map.flyTo([anchor.latitude, anchor.longitude], anchor.maxDistanceM ? 13 : 15, {
      animate: true,
      duration: 0.7,
    });
  }, [anchor, map]);

  if (!anchor) return null;
  const centre: [number, number] = [anchor.latitude, anchor.longitude];

  return (
    <>
      {anchor.maxDistanceM && (
        <Circle
          center={centre}
          radius={anchor.maxDistanceM}
          pathOptions={{ color: '#df6e4b', fillColor: '#df6e4b', fillOpacity: 0.08, weight: 2, dashArray: '7 7' }}
        />
      )}
      <CircleMarker
        center={centre}
        radius={9}
        pathOptions={{ color: '#fffdf8', fillColor: '#df6e4b', fillOpacity: 1, weight: 3 }}
      >
        <Popup>
          <div className="anchor-popup">
            <strong>{anchor.name}</strong>
            <span>{anchor.address}</span>
            <small>{anchor.subzone} · {anchor.planningArea}</small>
            {anchor.maxDistanceM && <small>Search radius: {(anchor.maxDistanceM / 1000).toFixed(1)} km (straight-line)</small>}
            <em>Location resolved by OneMap</em>
          </div>
        </Popup>
      </CircleMarker>
    </>
  );
}
