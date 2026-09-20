import type { ProcessingStatus } from '../rooms/api';
import type { GeoAnchor } from './layer';

/** The room's most accurate GPS fix, with the compass rotation when the phone reported one. */
export function bestAnchor(status: ProcessingStatus | null): GeoAnchor | null {
  const anchors = status?.geography?.anchors ?? [];
  if (!anchors.length) return null;
  const { anchor } = anchors.reduce((best, next) =>
    next.anchor.horizontal_accuracy_m < best.anchor.horizontal_accuracy_m ? next : best);
  const heading = anchor.heading;
  const [x, , z] = heading?.reference_direction_world ?? [0, 0, 0];
  return {
    latitude: anchor.latitude,
    longitude: anchor.longitude,
    // The reference direction points along the measured bearing; north is that bearing undone.
    north: heading && Math.hypot(x, z) > 0.3 ? (heading.degrees * Math.PI) / 180 - Math.atan2(x, -z) : null,
  };
}
