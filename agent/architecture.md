# Room agent

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
A finalized speech transcript can be supplied as the command. Audio transcription,
continuous voice sessions and physical robot drivers are not implemented here.

The agent reads scene context, retrieves images, resolves object identities and
requests bounded skills. The server records idempotent receipts tied to the
observed scene revision. No motor command is dispatched by this implementation.
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

The agent registers eight room tools. Astra's model catalog additionally requires
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

Run it on a computer connected to both the robot network and the server. The
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
