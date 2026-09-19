# Room agent

## Local robot simulation

Start the isolated physics server and live viewer:

```sh
uv run --project be --group sim python -m htn_backend.simulation.run
```

Open `http://127.0.0.1:8792`, then in another terminal:

```sh
uv run --project be --group sim python -m htn_backend.simulation.run \
  --command "Explore the available viewpoints to find the blue block; report what you saw."
```

This launcher checks the server's simulation domain and never constructs the
physical robot link, even when hardware credentials exist in the environment.
Use it for simulation rather than the hardware-aware `agent/run.sh` launcher.
The same Codex/Astra harness and room tools issue asynchronous, idempotent actions.
Every receipt distinguishes `simulation_success` from `physical_success: false`.
The server and receipts are ephemeral; restart for a fresh episode.

The historical simulation fixture has one powered front steering wheel, four
passive spherical ball casters, a shoulder/elbow/wrist arm, and two segmented
curling tentacles with tendon actuators. Base motion comes from wheel contact;
there are no planar chassis actuators or grasp welds. The free base can slip and
tip. A single steering contact does not independently prescribe chassis yaw.
Footprint-inflated A* uses the known static fixture map; feedback follows position
and verifies a stopped arrival within 6 cm. Difficult routes can still fail.

The camera is attached to the chassis at approximately 1.2 m height, with a
65-degree vertical field of view. Observations include measured camera-to-room
transforms. Simulator segmentation gates labels by actual rendered visibility;
objects outside the camera or occluded by geometry are not published until seen.
Last-seen object poses and camera evidence remain explicitly historical. These
are ideal simulator labels/poses, not our trained detection or SLAM pipeline.
Exploration waypoints sample the known free-space map, independently of movable
object positions. They are navigation targets, not detected physical objects.

Link lengths (40/35/10 cm), masses, motor limits, friction and tentacle stiffness
are assumptions awaiting hardware measurements. The tentacles approximate a
continuum structure with five rigid segments each. Curl/uncurl is tested, but
simulator grasp/release is validated for the rigid block fixture. Simulation
pick/place are enabled for that scope; physical tentacle manipulation is not.
A bounded target-relative approach and measured Cartesian endpoint servo correct
alignment and load error. Local secant calibration reports residual and excitation;
unexcited directions are not claimed calibrated. Narrow corridors can still block
manipulation even after successful position-only navigation.
The historical ideal-base/parallel-gripper delivery results do not transfer to
this hardware model. Current challenges and results are under
`be/benchmarks/simulation/feedback/`. Earlier hardware-model results remain in
`be/benchmarks/simulation/tentacle/` as historical evidence.

`read_feedback` exposes measured simulation motion, joints, contact forces, hand
position, controller error and phase during actions. A bounded monitor uses
Codex `turn/steer` to coalesce simulation phase changes into the active turn while
the controller continues. These are marked untrusted observations. Hardware reports
remain explicitly unverified and are not automatically injected as actuator events.
The simulator still advances during actions and holds between skills; this is not
a wall-clock real-time or moving-hazard validation. π0.5 is researched, not installed
or trained for this custom robot.

Run the controller suite or a fresh real Astra episode with saved receipts and replay:

```sh
uv run --project be --group sim python -m htn_backend.simulation.evaluate
uv run --project be --group sim python -m htn_backend.simulation.evaluate --agent
```

Results default to `/tmp/htn-simulation-result.json`; the agent run also writes
PNG/GIF views there. Committed summaries are in `be/benchmarks/simulation`.
`uv run --project be --group sim pytest be/tests -q` includes physics tests;
without the optional simulation dependencies those tests explicitly skip.
These runs tune controller parameters and prompt behavior, not model weights.

The [MuJoCo Python API](https://mujoco.readthedocs.io/en/stable/python.html)
provides the simulator. [Menagerie](https://github.com/google-deepmind/mujoco_menagerie)
and [Stretch MuJoCo](https://github.com/hello-robot/stretch_mujoco) provide more
realistic robot models for the next stage; neither is claimed as integrated here.

`codex/` is the official OpenAI Codex repository pinned as a Git submodule.
It retains its upstream source, license and history. Initialize with
`git submodule update --init --depth 1 agent/codex`.

Run `./agent/run.sh ROOMCODE "Find the bottle and explain what you can do"`.
The launcher uses the source build at `codex/codex-rs/target/release/codex`
when present, otherwise the installed official `codex` executable. Authenticate
that executable with `codex login`; credentials are not stored in this repository.
The tested installed executable is `codex-cli 0.154.0`. Source checkout and
installed release are deliberately distinguished; cloning is not a source build.

The adapter lives in `be/src/htn_backend/agent`. It speaks the official app-server
JSON-lines protocol and registers room-scoped dynamic tools. The reasoning model
is always `gpt-6-astra`; model rerouting fails instead of silently substituting.
A finalized speech transcript can be supplied as the command. Voice integration
is separate from the supervised local motion adapter described below.

The agent reads scene context, retrieves images, resolves object identities and
requests bounded skills. The server records idempotent receipts tied to the
observed scene revision. Server-side skills dispatch no motor command:
`inspect` retrieves stored evidence; `navigate`, `pick`, `place` and `stop` report
blocked until a calibrated hardware executor is implemented. No deferred motion
queue is accumulated for later execution. A future actuator interface must add
authenticated robot identity, local command expiry, feedback, cancellation,
calibrated transforms and independent obstacle stopping before accepting motion.

Server receipt age is not capture age. Device timestamps are preserved but not
treated as synchronized clocks. Stored observations and estimated furniture
bounds do not prove current free space, graspability or physical task success.
The server now serves camera observations independently of mapping progress;
the robot controller must ultimately obtain current sensors locally.

Raw-upload cleanup preserves sparse alignment reference views. `observe` falls
back to these retained RGB-D views; `list_views` pages through their sequences.
They remain explicitly historical, and their poses are already in room coordinates.

## Robot prompt and tool surface

`be/src/htn_backend/agent/profile.py` defines one runtime profile. It replaces
the upstream coding base prompt with task-specific observation, grounding,
ambiguity, and action-receipt instructions. It disables workspace environments,
shell, file viewing/editing, web search, delegation, plugins, host skill prompts,
and inherited MCP servers for this run without changing the user's saved settings.
The official source and its licenses remain intact.

The agent registers nine room tools. Astra's model catalog additionally requires
Codex's sandboxed JavaScript `exec`/`wait` wrapper; its host stays enabled so
dynamic tool calls work. The runtime also exposes clock and clarification helpers.
The wrapper has no shell, file, or network API; its callable tools are checked by
`be/tests/agent/test_profile.py` using the actual installed Codex executable and
a local mock model provider. That test verifies both the outgoing prompt/tool
surface and a real round trip through the tool host. CLI absence skips this test;
it does not count as validating a different or future source build.

The live Astra check on recorded room A211342B retrieved laptop evidence,
observed retained sequence 65, and grounded a bottle region at approximately
0.51 m with 12.3% depth coverage. The agent reported historical-image and
surface-support limitations. This is an integration check, not object-pose
accuracy or physical robot validation.

## Supervised motion

The confirmed chassis has one fixed powered wheel, a separate MG90S-steered
small wheel, and four swivel casters. See `robot/reference` for photographs and
unmeasured calibration fields. It cannot execute differential-drive turns in place.

With `HTN_ROBOT_URL` set, the launcher registers `robot_status`, `drive_base`,
`set_arm`, `run_winch` and `stop`. `drive_base` commands signed wheel duty and
steering-servo offset for at most two seconds. The adapter requires fresh
`single_steer_v1` telemetry and human supervision; incompatible firmware is
blocked. Arm/winch tools also require explicitly reported hardware capabilities.
The supplied steering firmware does not enable them.

`robot/steering` builds the stopped-by-default ESP32-S3 serial controller using the
confirmed GPIO wiring. A loopback serial/WebSocket bridge connects it to the
laptop agent. Read `robot/steering/bench.md` before opening the serial port: the
old one-shot test sketch can move on reset. No physical board was flashed by this
implementation. Active host commands expire after 250 ms even if the background
heartbeat remains alive; firmware commands expire after 300 ms. A missing stop
report cannot produce a completed motion result.

The badge can hold that supervision instead of the `--supervise` flag: the bridge's
token-guarded badge endpoint turns the badge's AUTO heartbeat into firmware supervision
and forwards its E-STOP, and never forwards badge motion (see `robot/steering/bench.md`).

These are supervised actuator commands, not calibrated navigation. Raw encoder
counts and commanded servo offsets do not establish meters, chassis yaw, contact
clearance or physical task success. Server `navigate`/`pick`/`place` remain blocked
for physical execution. The historical simulator's powered steering wheel and
ball casters differ from the photographed hardware; its delivery scores are not
validation of this chassis. Updating that model requires measured geometry and
steering/rolling calibration.

## Reference architecture

The [linked demo](https://x.com/BdcauntBen/status/2092806371154460865) was inspected
from its video. Its diagram shows LiDAR occupancy mapping, location-associated
camera images, CLIP image memory, Codex goal selection, A* planning, Pure Pursuit
control and a separate safety gate. It demonstrates navigation, not a validated
general-purpose manipulation system. Search now combines SQLite FTS with pinned SigLIP 2 embeddings of object evidence.
Visual similarity only ranks candidates; it does not establish object identity.

[DimOS](https://github.com/dimensionalOS/dimos), inspected at
`6ea05bb83318c065f2148dffd2d2b67ad0b77b57`, separates stream-connected hardware
modules from agent skills and exposes those skills through MCP. Its observation
skill returns images; navigation dispatches goals and has separate cancellation.
This supports using bounded tool contracts without replacing our mapping stack.
It also contains a navigation capability-lifetime TODO: a method returning after
dispatch must not be mistaken for completed motion. We have not installed DimOS
or claimed compatibility with a physical DimOS robot.

[Official app-server documentation](https://developers.openai.com/codex/app-server)
describes the transport used here. This wrapper keeps the upstream agent harness;
it does not reimplement reasoning or replace it with direct model API calls.

## Firmware telemetry

The teammate `robot/` firmware accepts 20 Hz normalized motor commands over
`ws://192.168.4.1:81/` and publishes telemetry. Its `goal` field is ignored,
encoder calibration is unset, and joint angles are commanded estimates.
The read-only bridge uses non-command heartbeats, never takes motor ownership:

```sh
uv run --project be python -m htn_backend.agent.bridge ROOMCODE
```

Run it on a computer connected to both the robot network and the server. From the
robot's second (hotspot) network the robot only accepts clients that carry the agent
token, so use `HTN_ROBOT_URL=ws://<robot-ip>:81/?token=...` there. The
ESP32 access point alone does not provide a route from GCP to the robot.
The scene exposes reported telemetry without treating it as authenticated
actuator feedback or enabling navigation.

## Visual retrieval

`be/deploy/retrieval/install.sh` provisions a separate loopback-only GPU service.
It uses an isolated Transformers environment while reusing host CUDA Torch.
Object-crop vectors are persisted in SQLite, keyed by image digest and model
revision, encoded in batches of eight, and pruned when evidence disappears.
Search returns its retrieval mode explicitly if the visual service is unavailable.
The L4 six-crop check is recorded in `be/benchmarks/retrieval/l4-evidence.json`.
Detector labels are not ground truth; these timings are not an accuracy benchmark.

## Image-region grounding

`ground_region` accepts an observation sequence and a normalized bounding box
in the upright image returned by `observe`. Projection uses native depth-grid
intrinsics, gravity-derived image rotation, depth confidence, and the registered
capture pose. Sparse or ambiguous depth fails explicitly. The output is a
measured surface estimate with depth spread and coverage, not a confirmed object
identity, completed shape, robot-relative pose, or executable grasp. This lets
Astra investigate smaller objects inside a table crop without substituting the
table's mapped center. It does not repair the room's instance segmentation.
