# Feedback-controlled manipulation evaluation

The same 30 procedural cases (seeds 20–29; open, detour and blocked layouts)
were rerun against the previous four-caster controller. Some seeds were used in
development, so this is a regression comparison, not a held-out success estimate.
The hardware geometry is unchanged; the controller, approach planning and feedback
changed. All object/robot poses used by the direct controller are simulator truth.

| Outcome | Previous controller | Updated controller |
| --- | ---: | ---: |
| Navigation in open/detour cases | 20/20 | 20/20 |
| Completed open-room deliveries | 0/10 | 10/10 |
| Completed detour-room deliveries | 0/10 | 0/10 |
| Rejected fully blocked routes | 10/10 | 10/10 |
| Cases with environment collisions | 0/30 | 0/30 |

Thus delivery improved from 0/20 to 10/20 across the two non-blocked layouts.
The 10 detour failures remain failures: eight stopped on the local stopping-path
check during repositioning; two had no feasible arm-approach corridor. Position
navigation works there, but manipulation approach planning still needs work.

The updated pipeline uses steering travel cost to prevent forward/reverse chatter,
conservative transit A*, oriented footprint checks near manipulation, target-relative
alignment, a measured Cartesian hand servo, and contact/lift/support verification.
The arm uses nominal geometry plus bounded online secant updates. It exposes
residual and excitation instead of claiming every direction has been calibrated.
Curl commands alone never count as a successful grasp. No grasp weld or action
teleport is used. The release permits the rigid block to settle under gravity;
it is not validated for fragile objects or force-controlled surface placement.

The full backend suite passed 134 tests, including cancellation, feedback during
active motion, correct room/turn scoping, stale/hidden scene evidence, steering
reversal, contact-based delivery, and endpoint correction. Separate load probes
recompute MuJoCo constants and vary arm mass and inertia together by ±30%.
The controller is not told the changed values. These are ideal-sensor simulator
tests, not hardware calibration. Two existing HTTP test-client deprecations remain.

Two real Codex/Astra runs used the same room tools:

- A full open-room delivery completed in 59.5 seconds of wall time, with four
  successful action receipts, verified final support/rest and zero collisions.
- A second seed completed pickup with retained bilateral contact and a 26.5 cm
  lift. The actual harness acknowledged nine coalesced mid-turn phase updates;
  `feedback-events.json` records those events.

`agent-results.json`, `controller-summary.json`, and `controller-cases.jsonl`
retain the outcomes. Replays are generated under `/tmp`, not committed recordings.
`checks/holdout.py` defines additional fresh offset/load probes independently of
the development seeds; their results are recorded separately when available.

Pick/place are enabled only for the simulator's supported rigid block and tables.
This does not enable physical hardware or claim arbitrary-object manipulation.
The simulator uses ideal joint/hand state and known static geometry; observations
are visibility-gated simulator labels, not a tested learned perception stack.
Actions run while Astra reasons, but simulation time still holds between skills.
Moving hazards, camera/encoder delays and sensor noise remain unvalidated.

Next priorities are a motion planner that reasons jointly about base heading and
clearance in narrow corridors, calibrated tentacle mechanics/contact sensing,
and real RGB-D hand/object tracking. A π0.5 integration also needs a compatible
embodiment adapter and demonstrations; see `research.md` for the source review.
