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

## Supervised motion

With `HTN_ROBOT_URL` (e.g. `ws://172.20.10.12:81`) and `HTN_ROBOT_TOKEN` set, the
launcher also offers `robot_status`, `drive`, `turn`, `set_arm`, `run_winch` and
`stop` (`be/src/htn_backend/agent/motion`). They talk to the robot base directly
from the laptop over its WebSocket, never through the server, and:

- only move while a human has the badge in AUTO mode and armed; the robot drops
  the agent within 300 ms of that heartbeat stopping, and any badge button is an
  E-STOP that only a human can clear (`robot/src/net/authority.cpp`);
- are bounded to 1 m, 180 degrees, 30% duty and 12 s per call, block until done
  and report what the robot's telemetry said, including why a move was cut short;
- estimate distance and angle from time, because the encoders are uncalibrated.

This covers command expiry, cancellation and feedback from the list above. It
does not provide calibrated transforms or independent obstacle stopping, so it is
for short supervised moves only; `navigate` to an object stays blocked.

## Reference architecture

The [linked demo](https://x.com/BdcauntBen/status/2092806371154460865) was inspected
from its video. Its diagram shows LiDAR occupancy mapping, location-associated
camera images, CLIP image memory, Codex goal selection, A* planning, Pure Pursuit
control and a separate safety gate. It demonstrates navigation, not a validated
general-purpose manipulation system. Our current search is SQLite FTS, not CLIP.

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
