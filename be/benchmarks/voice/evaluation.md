# Voice integration evaluation

September 2026. Actual GPT-Live 1 API and authenticated Codex Astra app-server,
MuJoCo 3.3.7. Input was synthetic spoken English, not text injected as a transcript.
These are integration cases, not a statistically meaningful robotics benchmark.
Structured task receipts are summarized in `results.json`; recordings stay local.

| Case | Observed result |
| --- | --- |
| Camera question, seed 0 | Real audio transcribed, delegated, camera/scene tools used, spoken observation returned. About 12 s from delegation to Codex result and 0.7 s more to spoken result. |
| Delivery, seed 0 | Exploration/navigation succeeded. Pick failed outside local approach; no delivery claimed. |
| Seed 0 follow-up after recovery prompt | Agent navigated to the block and retried. Pick failed at predicted-footprint collision check. No delivery claimed; collision gate preserved. |
| Delivery, independent seed 21 | Exploration, navigation and pick succeeded. First place attempt failed `support_approach_unreachable`; agent navigated to destination and retried successfully. Final receipt: `released_object_support_and_rest_verified`, empty gripper, zero collision steps. Spoken result matched receipt. Codex result at ~132 s from runner start. |

Seed 21's later session shutdown timed out after a long interruption: the runner
elapsed time reached ~817 s despite a 240 s test window. It is a task success,
not a clean transport success. Cleanup and audio pacing were subsequently tightened:
sender failures now propagate, and stale audio is not burst-uploaded after a pause.

The first memory test revealed that the voice model could acknowledge remembering
without delegating. The revised prompt explicitly lists persistent storage as a
backend capability. A later real voice request wrote the preferred delivery table
to SQLite. Cross-session recall then exposed punctuation-sensitive search; compact
Unicode-normalized lookup and an empty-query fallback were added. See final checks
below for the rerun; the initial failures are intentionally retained here.

## Automated scope

The combined voice/agent suite passed 66 tests. One earlier run had a pre-existing
motor-supervision stop-reason race (`control_revoked` versus `supervision_lost`);
its isolated rerun and the subsequent combined run passed. No hardware was moved.
After the final note-search change, the 21 voice tests passed again.

Tests cover duplicate delegation, transcript accumulation, supersession/stop,
late-result suppression, idempotent close, backend failure, executor gate ordering,
physical endpoint rejection, room-scoped durable notes, normalized search, stale
Codex turns, final-result selection, browser origin checks, audio format/length,
and exact microphone PCM chunk size/clipping. Ruff and JavaScript syntax checks pass.

Browser DOM/screenshot inspection verified the camera image, controls and layout;
no console errors were present. The desktop relay is also exercised with real
streamed PCM and provider audio. Human microphone acoustics and speaker echo are
not yet tested. Use headphones for the first manual session.

## Limits

The two seeds do not establish reliable grasp success. Seed 0 remains a collision-
constrained failure; seed 21 is a positive fixture, not a replacement for hard cases.
The simulator uses ideal perception and the older base/tentacle-arm model. This
work does not calibrate the new physical base, train a manipulation policy, or
validate a physical gripper. New delegated questions currently preempt running
work; readonly status routing remains an app-integration improvement.

## Final live reruns

- Fresh desktop-relay session recalled the existing database preference: “You asked
  me to remember the delivery table as your preferred drop-off.” Codex result at
  9.18 s from test start; GPT-Live spoke the matching answer. Button stop returned
  `simulation_success: true`; session closed without a reported provider error.
- Final primary-WebSocket camera command returned a camera-grounded description
  at 22.96 s, spoke it, and ended with `session.closed`. Cleanup errors: none.
- These runs use the final delegation prompt, normalized memory search and cleanup.
