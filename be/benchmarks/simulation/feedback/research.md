# Astra, learned motor policies and online feedback

## Linked example

The [post](https://x.com/LeoKharon/status/2100555718441017619) discusses
[GPT as Policy](https://github.com/anonymous-report-421/GPT-as-Policy), inspected at
`8f3d362b077d8efb77e2a7274d5b2c20e2243846` in a temporary reference checkout.
We inspected the report, implementation and post text, not just the social summary.

Its hybrid controller chooses between short prefixes of a task-specific π0.5
prediction and Astra end-effector corrections. Observations include multiple
camera images and proprioception. Physics waits during deliberation, so this is
not evidence of real-time hardware control. Results must be separated by suite:
the repository's selected RoboDojo cases report 26% direct and 48% hybrid success.
Do not apply the post's 98% claim to that experiment or to this robot.

## π0.5 and transfer

[Physical Intelligence's π0.5 description](https://www.physicalintelligence.company/blog/pi05)
combines semantic subtask selection with continuous flow-matching action chunks.
[OpenPI](https://github.com/Physical-Intelligence/openpi) supplies checkpoints and
adaptation examples, but explicitly does not guarantee transfer to a new robot.
Its public π0.5 implementation supports the flow-matching head. A seven-joint
Franka or bimanual policy does not become a shoulder/elbow/wrist/tentacle policy
by dropping action dimensions. Joint order, units, normalization, cameras and
training demonstrations must match the embodiment. No π0.5 checkpoint was run
or installed as part of these experiments.

[Real-time chunking](https://www.physicalintelligence.company/download/real_time_chunking.pdf)
addresses overlapping inference and execution. It is relevant once a compatible
learned policy exists; blocking every motor step on Astra is not our intended
architecture. Any future candidate chunk needs observation age, embodiment,
joint-limit and cancellation checks before its short execution prefix is accepted.

## Calibration choice

[Uncalibrated visual servoing](https://webdocs.cs.ualberta.ca/~vis/robotics/uncalib/uncalibvs.htm)
provides the basis for online secant/Jacobian updates. Our implementation starts
with nominal arm geometry, updates a local Jacobian from measured joint and hand
changes, applies damped corrections, rejects discontinuities and reports excitation
and residuals. Calibration freezes during a verified grasp. This is local system
identification, not retraining Astra or learning an entire motor policy. In these
runs the hand pose is ideal simulator feedback, not a deployed visual tracker.

[RMA](https://arxiv.org/abs/2107.04034) and
[its manipulator extension](https://arxiv.org/abs/2312.04670) motivate adaptation
under changing dynamics. They require trained policies/adaptation modules; they
are not a replacement for measuring this robot's mechanics. We implemented and
tested bounded secant feedback, not an RMA policy or a SOTA benchmark reproduction.

## Implemented control boundary

Astra selects room goals. A* provides conservative transit routes; a separate
oriented-footprint approach checks manipulation clearance. Target-relative feedback
aligns the base. Cartesian feedback controls the arm, followed by contact/lift and
release/support verification. There is no simulated grasp weld or action teleport.
Physical hardware remains outside this simulator executor.

The server exposes measured joints, commanded targets, hand position, base motion,
contact forces, phase, endpoint error and calibration quality. `read_feedback` and
action receipts expose these values while the controller runs. A bounded phase
monitor coalesces simulation events into
[Codex mid-turn feedback](https://developers.openai.com/codex/app-server).
These are marked untrusted observations, scoped to the active turn, and cancelled
when it ends. Reported ESP32 telemetry is readable but is not automatically
promoted into authenticated execution events.

The simulator still uses accelerated, action-driven time and holds between skills;
we have not shown recovery from moving hazards during long reasoning pauses.
Known static geometry and ideal state measurements also remain assumptions.
The narrow-corridor manipulation problem is not solved by a VLA integration.
