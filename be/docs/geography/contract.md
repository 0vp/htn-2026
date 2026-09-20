# Approximate geographic room context

The LiDAR map remains in its existing local, right-handed, Y-up metre coordinates.
GPS/compass data never enters SLAM, registration, collision checks or navigation.
This supports an approximate street-map/building layer, not precise outdoor
localization or a continuous GPS tracker. A guardian can combine local tracked
poses with this approximate reference, retaining the original error estimate.

## Dashboard contract

`GET /v1/rooms/{room}/geography` returns:

```json
{
  "schema_version": 1,
  "approximate": true,
  "purpose": "outdoor_context_only",
  "coordinate_reference": "WGS84",
  "local_coordinates": "unchanged_metres",
  "warning": "Indoor GPS and compass may be inaccurate. Not navigation or alignment.",
  "anchors": []
}
```

The same object is `geography` in room responses and processing status/events.
Each anchor record identifies `room_id`, `device_id`, `session_id`, `epoch`, upload
`sequence`, server `received_at`, and its `anchor`. One best coherent reading is
retained per device/session/epoch. Records survive raw-frame cleanup and restart.
An empty array is normal when permission is denied, location is unavailable, or
no AR pose can yet be paired. Never interpret absence as latitude/longitude zero.

`anchor` contains:

| Field | Meaning |
| --- | --- |
| `latitude`, `longitude` | WGS84 degrees at the phone location, **not the room origin** |
| `horizontal_accuracy_m` | Core Location horizontal error-radius estimate, metres |
| `timestamp_unix_s` | Original GPS fix time, UTC Unix seconds |
| `pose_timestamp_s` | Monotonic AR frame time nearest that reading |
| `pose_time_offset_s` | AR pose wall-clock time minus reading time; within ±0.35 s |
| `camera_to_world` | 16 column-major entries, ARKit camera-to-local transform in metres |
| `heading` | Optional independently timed compass reading |

`heading` contains `degrees` (clockwise from north), `accuracy_degrees`,
`reference` (`true_north` or `magnetic_north`), `orientation: landscape_right`,
its own `timestamp_unix_s`, `pose_timestamp_s`, `pose_time_offset_s`,
`camera_to_world`, and a unit `reference_direction_world` vector. The latter is
the physical heading-reference axis expressed in the local AR world. It is **not
necessarily camera forward**. The phone configures both Core Location's heading
orientation and ARKit's view-matrix orientation as landscape-right, independent
of interface rotation. Physical compass/axis calibration is still to be verified.

## Positioning the layer

1. Fetch `/v1/rooms/{room}/processing` and match `alignments` by
   `JSON.stringify([device_id, session_id, epoch])`. Use a verified
   `room_from_local` transform (column-major), including identity for the anchor
   stream. If absent/unregistered, show GPS as context only; do not assume identity.
2. Transform the GPS pose translation into room coordinates. That point corresponds
   to the geographic fix. Subtract it from local positions before adding metric
   offsets to the map projection. Do not pin the room origin to the phone's GPS.
3. Rotate the heading reference vector by the same transform and project onto XZ.
   Normalize only when its horizontal length is at least 0.25; otherwise rotation
   is indeterminate. Use `true_north` for a north-up street map. A magnetic heading
   needs a separately justified declination correction; never silently treat it as true north.
4. For horizontal unit reference `(dx,dz)`, true bearing `theta`, and room offset
   `(x,z)`, let `along=dx*x+dz*z`, `right=-dz*x+dx*z`.
   East = `sin(theta)*along + cos(theta)*right`;
   North = `cos(theta)*along - sin(theta)*right`. This accounts for room Y-up axes.
   Use the map library's geographic/metre projection for the remaining conversion.
5. Show an accuracy radius, heading uncertainty and timestamp. Indoor GPS may be
   off by several to tens of metres or worse; nearby metal can disturb compass
   readings. A street/building basemap supplies approximate surroundings, not
   newly sensed geometry. Never use inferred walls/buildings as collision evidence.

There is no altitude/floor-elevation calibration in this version. Do not infer a
building floor or vertical offset from this payload. Do not combine unregistered
phones' anchors or average bearings without respecting their separate AR epochs.

## App and wire behavior

The existing R3D1 frame header gains optional `geographic_anchor`. It uses normal
upload acknowledgments/retries. The app checks `room.geography.schema_version == 1`
before requesting location or adding the field, preserving operation against the
older deployed server. No user-facing configuration or changes to the voice UI.

When scanning starts, foreground-only Core Location begins with when-in-use
permission. The first usable GPS fix is emitted when a normal-tracking AR pose
can be paired; room creation alone cannot provide an AR pose. Heading can arrive
later. Updates are at least ten seconds apart and require a 20% position/heading
accuracy improvement or a missing-heading/true-north upgrade, without degrading
other supplied accuracy. Each new AR epoch starts a new anchor. Stopping capture
stops location updates. No background tracking or geographic history per frame.

A six-second AR pose buffer pairs readings with their actual measurement times,
not upload time. GPS must be within five seconds of capture; the heading can differ
from that fix by at most three seconds and gets its own paired pose. These are
local capture checks; the server accepts delayed uploads and never compares GPS
wall time to server time. Delayed/inferior fixes cannot overwrite the stored best.

Canonical legacy packet encoding omits the new field when absent, preserving
existing frame digests and retry identity across deployment.

## Verification and rollout

Simulator build and transport tests cover coding, capability decoding and quality
selection. Backend tests cover R3D1/WebSocket ingestion, durable retry, independent
epochs, validation, inferior/out-of-order updates, restart and raw retention.
Real GPS, magnetic interference and physical heading axes require an iPhone test;
simulator tests do not establish geographic accuracy.

Deploy the backend first, then rebuild the phone app. Rejoin/reopen a room after
upgrading the backend so its capability marker is refreshed. Do not assume deployment from a git push.

Geographic-anchor support was deployed to `qasim-test` in `us-central1-c` and
verified through public HTTPS/WebSocket endpoints. A synthetic room accepted three
frames and a duplicate retry; an improved anchor replaced the initial one, an
older delayed fix did not, processing status exposed the anchor, and frame bytes
and local transforms remained unchanged. The synthetic room was then closed.
Both backend and mapping services were healthy after restart. Real iPhone GPS
and heading calibration remain unverified.

Primary references:
- [Apple heading orientation](https://developer.apple.com/documentation/corelocation/cllocationmanager/headingorientation)
- [Apple true heading](https://developer.apple.com/documentation/corelocation/clheading/trueheading)
- [Apple horizontal accuracy](https://developer.apple.com/documentation/corelocation/cllocation/horizontalaccuracy)
