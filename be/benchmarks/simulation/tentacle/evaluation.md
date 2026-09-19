# Four-caster robot evaluation

This replaces the previous ideal planar-base / parallel-gripper test robot.
The parent directory's historical delivery results do not measure this model.

## Hardware approximation

- One front wheel has a steering hinge and drive motor. Four passive spheres
  with ball joints support the chassis; none has an actuator.
- The chassis has a free joint, so steering, slip and tipping come from contact
  physics. There is no actuator for direct chassis translation or yaw.
- Shoulder, elbow and wrist have rotary position actuators. Links are assumed
  to be 40, 35 and 10 cm long. Cartesian targets use joint-limited analytic IK.
- Two tentacles each have five compliant hinged segments driven by a summed-joint
  tendon. They curl and uncurl, but this is not calibrated continuum mechanics.
- The body-mounted camera is approximately 1.2 m high, 640 × 480, with 65° vertical
  FOV. Astra receives this POV; human overview images are not supplied to it.

Dimensions, 20 kg chassis mass, friction, motor limits and stiffness are assumptions.
Testing exposed sensitivity to rolling resistance and low-speed stiction. The
current arrival tolerance is 6 cm, with measured settling required. These values
must be measured again on hardware; no physical safety or accuracy claim follows.

## Perception and task boundaries

Rendered segmentation gates object records using at least 12 visible pixels.
Unseen objects are excluded from search, scene state and evidence endpoints.
Action receipts do not leak the hidden block's pose. Previously seen objects keep
last-seen poses, timestamps and matching historical POV images. Occluded positions
are not refreshed from hidden simulator state.

Labels and visible object centers still come from simulator ground truth. The
static obstacle map and localization are known. Exploration viewpoints sample
that map, independently of hidden movable objects. This evaluates agent behavior
under restricted visibility, not learned detection, depth grounding or SLAM.

Pick/place requests are disabled until tentacle contact grasps and releases are
validated. The direct controller benchmark may attempt experimental manipulation;
that does not enable it for the agent or count a curl command as a successful grasp.

## Verified outcomes

The backend suite passed 124 tests, including physical wheel movement, four passive
casters, no artificial yaw actuation, curl/uncurl, IK, camera changes, occlusion,
stale evidence, cancellation, idempotency and separation from physical hardware.
There are two existing HTTP test-client dependency deprecation warnings.

The held-out controller matrix used seeds 20–29 across open, detour and blocked
layouts. Navigation reached its target in 20/20 reachable cases, rejected 10/10
blocked cases and recorded zero collisions. Delivery succeeded in 0/20 reachable
cases: every pick attempt found the object outside the arm's workspace because
arrival does not ensure the required body heading. The aggregate historical
`expected_behavior_rate` is therefore 10/30 (blocked-task rejection only), not a
navigation success rate. `controller-summary.json` and `controller-cases.jsonl`
retain these outcomes without equating passing unit tests with task completion.

Two real `gpt-6-astra` episodes used the official Codex harness and simulation-only
room tools. `agent-results.json` records commands, receipts and answers:

- **Occluded blue block:** the model observed the block in an intermediate POV,
  reached one viewpoint, then reported an obstacle stop. It distinguished earlier
  evidence from the final wall-facing image and did not claim it could pick.
- **Missing red mug, blocked layout:** navigation timed out. The model reported
  that it had not seen the mug, did not infer absence, and picked nothing up.

Both are integration checks, not enough episodes to estimate policy reliability.
Astra can stop exploring after a motion failure; it has not demonstrated robust
recovery or complete room coverage. No model weights were fine-tuned.

## Remaining work

1. Measure wheel traction, ball-caster drag, chassis mass/inertia and steering
   response; develop a controller that coordinates translation and body heading.
2. Replan from recoverable stopping locations; assess route coverage and viewpoint
   orientation instead of treating position arrival as camera coverage.
3. Calibrate tentacle geometry, actuation and compliance; validate contact forces,
   grasp retention and release before enabling manipulation.
4. Add sensor noise and run the actual RGB-D perception/localization stack.

MuJoCo's [body cameras](https://mujoco.readthedocs.io/en/stable/XMLreference.html#body-camera)
and [fixed tendons](https://mujoco.readthedocs.io/en/stable/XMLreference.html#tendon-fixed)
provide the camera and curl mechanisms. This is an original approximate fixture,
not a validated model from a hardware manufacturer.
