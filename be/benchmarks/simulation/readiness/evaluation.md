# Readiness evaluation

**Physical mechanism correction:** supplied photos and user confirmation establish
one fixed powered wheel, a separate small steering wheel, and four swivel
casters. The existing simulation is a historical powered-steering-wheel / ball-
caster fixture. The following delivery numbers do not validate the actual robot.
No firmware was uploaded and no physical motor commands were sent.

## Selected controller

Tracking clearance, exact A* endpoint connections, additional approach samples,
minimum approach speed, oriented clearance recovery, measured-footprint stopping
and command expiry were evaluated together. A 32-angle navigation variant lost
an open-room delivery (9/10) and was rejected. The selected 24-angle variant
preserves 10/10 open-room deliveries and improves detours from 0/10 to 3/10.
There is one default controller, with bounded automatic recovery; no profile menu.

| Procedural test | Previous | Selected |
| --- | ---: | ---: |
| Open-room deliveries, seeds 20–29 | 10/10 | 10/10 |
| Detour deliveries, seeds 20–29 | 0/10 | 3/10 |
| Blocked routes rejected, seeds 20–29 | 10/10 | 10/10 |
| Collision cases across regressions | 0/30 | 0/30 |
| Additional open offsets, seeds 201–204 | — | 4/4 |
| Additional detour offsets, seeds 201–204 | — | 0/4 |

The additional offsets were reused while comparing controller variants and are
**not a clean final held-out benchmark**. All 38 cases had zero recorded collision
steps. Failed predicted-footprint checks remain failures, not successful avoidance
or successful delivery. Narrow-space handling is still insufficient for autonomy.
The raw reasons and outcomes are in `results/cases.jsonl`.

Four additional open-room rigid-block probes (6–8 cm side length, 40–160 g, and
0–45 degree yaw) completed deliveries with zero collision steps. This covers a
small fixture family, not arbitrary grasping, fragile objects or tentacle realism.

## Agent and sensor interfaces

Real Astra completed a detour delivery in 159.7 seconds with seven action receipts.
It explored, encountered an out-of-local-approach pick rejection, navigated closer,
and then completed pickup and delivery. It reported that final support evidence
came from physics receipts, not a visible block in the final camera view. There
were zero collisions. The control implementation matches the selected variant;
subsequent service changes enforce verified final stops and disclose the geometry
mismatch. This is a single episode, not a model success-rate estimate.

Rendered depth now uses the same image-region projection as production iPhone
frames. HTTP/tool tests verify a known wall to within 5 mm, reject invalid/absent
depth, expire old frames and preserve capture pose/time for historical views.
The depth renderer is ideal and the camera transform is known. Object targets
still use simulator labels and poses; camera-driven SLAM control is not complete.
The local renderer warns that ARB_clip_control is unavailable; this is not evidence
of millimeter-accurate iPhone LiDAR.

## Confirmed physical command interface

`robot/steering` builds for ESP32-S3 with the supplied GPIO14/47 drive, GPIO13 servo
and GPIO41/42 encoder wiring. It starts electrically stopped, requires explicit
supervision and expires motor commands after 300 ms. The host's 250 ms command
lease prevents an alive background heartbeat from prolonging a stalled skill.

The physical agent exposes `drive_base(duty, steering_deg, seconds)` with a two-
second bound. Incompatible left/right firmware is blocked; turn-in-place tools
were removed. Raw encoder deltas and servo pulse offsets are not calibrated
meters or chassis yaw. Missing duty or an unverified stop cannot count as completed
motion. The serial bridge and native fixture run the actual firmware JSON parser
and watchdog in the end-to-end tests; they do not emulate motor loads or validate
real wiring. No physical obstacle sensing is implemented by this bench controller.

159 backend tests passed, including the bridge tests with no skips. The firmware
cross-build, C++ control tests and C++ parser tests passed; all eight serial bridge
checks also passed after the final parser correction. `results/checks.json`
records the binary hash and the explicit no-upload/no-physical-motion status.

## Next deployment gates

1. Supervised physical wheel/servo/encoder verification with the new firmware.
2. Measure footprint, contact offsets, steering linkage, rolling radius, encoder
   scale, stopping distance and camera-to-base transform; update the simulator.
3. Re-run navigation and manipulation on that corrected mechanism.
4. Feed camera/depth-derived geometry and uncertainty into control instead of
   oracle poses, then test dynamic obstacles and communication latency.
5. Expand manipulation to measured arm mechanics and varied objects. Physical
   navigation/pick/place remain unavailable until those gates are passed.
