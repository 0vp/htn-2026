# Harness engineering

How Kevin, our two-wheeled robot, is driven by a language-model agent. Each point describes
what is built in this repository; the last section says how far each part has been tested.

## Highlights

### 1. A three-layer split, like modern robot stacks

| Layer | Runs on | Responsibility |
|---|---|---|
| World and tools | Cloud VM | Phone streams, fused LiDAR map, scene objects, tool APIs, job queue |
| Agent | Laptop on the robot | A persistent Codex session (GPT-6 Astra, medium effort) |
| Skills | Laptop (`robot/scripts/drive.py`) | Calibrated wheel commands, keyboard override, command lease |
| Reflexes | ESP32 firmware | 300 ms watchdog, duty ramp, reversal pause, latched E-STOP |

Agent motion commands stay on the laptop and the USB link to the robot, so network jitter
cannot stutter or strand a move.

### 2. Every action returns a fresh observation

The act-observe loop is taken from coding agents. All moving and sensing tools (`look`, `turn`,
`forward`, `path`, `scan`, `stop`) return a fresh camera frame, a robot-centred LiDAR floor map
and the clear distance ahead, left and right. Results report what was measured and why a move
stopped. When a tool fails, the error tells the model what to do next instead of ending the turn.

### 3. π0.5-style two-level planning, done in the prompt

The agent names its semantic subtask before choosing an action ("reach the corridor", "line up
on the red box"). When the picture contradicts the subtask, it replaces the subtask, not just
the action. It explores by heading for frontiers (doorways, corridor ends, unmapped regions of
the room map) and uses priors about where things usually are in buildings. It is told never to
give up: out of frontiers means widen the search.

### 4. Moves that calibrate themselves, with no wheel encoders

The phone's visual-inertial tracking (camera, gyroscope, accelerometer via ARKit) measures every
move after it finishes. A learned rate model (degrees per second, metres per second) updates
from each measurement, and a turn that lands far off gets one corrective turn.

We measured the failure that led to this design: stopping on live pose feedback turned a 60°
request into a 153° turn, because the pose reaches the laptop 0.5 to 1 s late. On the floor the
rates settled at about 49°/s turning and 0.33 m/s driving.

### 5. A LiDAR safety reflex that lets the agent be bold

`forward` shortens itself before anything LiDAR sees and stops if the lane closes, so the prompt
can tell the model to plan boldly. LiDAR does not reliably see glass or drop-offs, and the
prompt says so. A human at the laptop can always override with the keyboard.

### 6. Chained actions and talking while moving

`path` runs several turns and straight legs as one continuous move with no thinking pauses in
between. Every moving tool has a `say` line that is spoken the instant the motion starts, so the
robot narrates while it drives instead of before or after. In a scripted test, a search took 3
tool calls where it would have taken about 10 separate ones.

### 7. Separate voice and agent, with delegation as the gate

GPT-Live-1 runs phone to OpenAI over WebRTC, so audio never passes through our server. The
server joins the same session over a sideband socket. Only requests the voice model chooses to
delegate reach the agent, so background chatter and the robot's own echo are filtered by the
voice model's delegation decision, not by a keyword list. Progress and results go back as
commentary on that delegation, and the voice says them aloud.

### 8. One character from one source

The voice persona and the agent prompt are both rendered from a single identity file
(`be/src/htn_backend/agent/embodied/identity.py`): name, character, language, abilities. A test
enforces that the two match and that every tool the prompt names actually exists. That test
caught a tool (`room_map`) that had never been registered.

### 9. A persistent agent that can be interrupted

One long-lived Codex thread keeps memory across commands ("go back to where you started"). A new
request interrupts the running one and the same agent decides whether it replaces, changes or
cancels the task. Saying "stop" releases the wheels before any reasoning happens.

### 10. Two kinds of map

The live map, built from the newest phone frame, is the authority on what is near the robot.
The server's accumulated room mesh is drawn as a bird's-eye view with labelled objects, their
distance and the turn needed to face them; the agent uses it for route planning and memory.

## What is proven, and what is not

Proven on the floor with the real robot:

- Fire alarm search: the agent scanned, drove itself to the pull station and parked facing it.
- Fire hose search.
- "Come back" to where it started, using memory of the same session.
- A twirl and a dance.
- Self-calibrating turn and drive rates.

Verified live without the robot moving:

- Perception from the phone stream in about 0.5 s per look; LiDAR map showing real obstacles.
- The room map rendering with labelled objects.
- Voice command to laptop agent and back through the cloud job queue.

Not yet exercised on the real robot:

- The direct phone-to-OpenAI voice path (WebRTC cannot be simulated from the laptop).
- `path` chaining, which has only run in a scripted world.
- Interruption of a running task by a new request.

Known limits: linear speed is learned, not surveyed; the server's room map stops growing when a
new phone tracking session cannot be aligned to the first one; LiDAR misses glass and stairs.

## Sources for the design

- OpenAI, [Delegation and tools in GPT-Live](https://developers.openai.com/api/docs/guides/live-delegation)
- OpenAI, [Prompting GPT-Live](https://developers.openai.com/api/docs/guides/live-prompting)
- Physical Intelligence, [π0.5: a Vision-Language-Action Model with Open-World Generalization](https://arxiv.org/abs/2504.16054)

## Where things live

| Piece | Path |
|---|---|
| Embodied tools, perception, navigator, prompt, identity | `be/src/htn_backend/agent/embodied/` |
| Persistent agent session and Codex app-server client | `be/src/htn_backend/agent/run.py`, `protocol.py` |
| Laptop worker (claims jobs, runs Codex, narrates) | `be/src/htn_backend/agent/worker.py` |
| Cloud job queue for the worker | `be/src/htn_backend/agent/remote.py` |
| Voice persona and sideband bridge | `be/src/htn_backend/voice/persona.py`, `bridge.py` |
| Keyboard, local and cloud motion links | `robot/scripts/drive.py`, `drive.sh` |
| Firmware and wiring | `robot/src/`, `robot/README.md` |
