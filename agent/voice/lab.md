# Voice robot lab

This is an app-independent GPT-Live 1 → Codex Astra → MuJoCo integration.
It runs the actual hosted voice model and official authenticated Codex app-server.
No physical motor adapter is instantiated. The existing iPhone voice routes are
unchanged; app integration is a separate handoff after this lab is validated.

## Run

From the repository root, with `codex login` completed and `OPENAI_API_KEY` in the
server environment (or local, ignored `be/.env`):

```sh
uv run --project be --group sim python -m htn_backend.simulation.run --port 8794
```

In a second terminal:

```sh
uv run --project be --group sim --env-file be/.env \
  python -m htn_backend.voice.lab.server
```

Open http://127.0.0.1:8795. Start the microphone and use headphones. The page shows
the robot POV, transcript, Codex result, and stop receipts. Stop robot cancels the
Codex turn and sends an executor stop; ending/disconnecting also requests stop.
Only one desktop session can control the simulator at a time; do not run a CLI
fixture concurrently against that same simulator. Sessions end after ten minutes.
The API key stays server-side. The local server intentionally binds loopback only.

Examples: “What can you see?”, “Find the blue block and put it on the delivery
table”, “Remember my preferred drop-off is the delivery table”, “Stop”.

For repeatable spoken fixtures, use mono PCM16 WAV at 24 kHz, up to 60 seconds:

```sh
uv run --project be --group sim --env-file be/.env \
  python -m htn_backend.voice.lab.live /tmp/command.wav \
  --server http://127.0.0.1:8794 --seconds 240 --output /tmp/voice-result.json
```

This produces structured evidence and assistant WAV locally. Never commit audio,
API credentials, recordings, or personal memory databases. Desktop notes live in
`/tmp/htn-voice-lab.sqlite`; fixture notes live beside the result JSON in
`voice-sim-memory.sqlite`. They survive session restarts but `/tmp` is not durable
production storage. Notes are room-scoped historical preferences, not live poses.

## Architecture and prompts

- `voice/prompts.py`: short spoken behavior and separate execution instructions.
- `voice/lab/runtime.py`: transcript accumulation, delegation deduplication,
  bounded backend appends, supersession, cancellation and result reporting.
- `voice/lab/backend.py`: persistent Codex thread with room tools and room-scoped
  SQLite memory. Empty readonly workspace; general shell/browser tools disabled.
- `agent/run.py`: final-answer selection prevents progress promises being spoken
  as results; stale events from interrupted turns are ignored.
- `voice/lab/server.py`: local microphone relay; binary PCM plus JSON events.
- `voice/lab/live.py`: reproducible primary-WebSocket audio fixture runner.

Codex can read the scene and actual robot camera, search/inspect objects, explore
views, navigate, pick/place, inspect receipts/live feedback, stop, and save/recall
explicit user notes. Skills and MuJoCo control loops execute movement; model token
generation is not a motor-control loop. The voice model has no direct robot tools
or camera: client delegation hands the accumulated conversation to Codex.

A new delegated request currently preempts an in-flight task, including a status
question. This is a conservative lab limitation; production should classify
readonly status separately from task replacement. Voice stop depends on network
and transcription latency and is not a physical emergency stop. The button bypasses
speech recognition. Stop receipts are polled to completion before confirming.

## Relevant provider endpoints

| Interface | Contract used |
| --- | --- |
| `wss://api.openai.com/v1/live/sessions` | Primary socket; bearer key only on server |
| `session.start` | `model: gpt-live-1`, instructions, `delegation.type: client`, mono PCM24k, Marin |
| `session.input_audio.append` | Base64 20 ms PCM chunks, continuously paced including silence |
| `session.input_transcript.delta` | Incremental transcript retained as task context |
| `session.delegation.created` | Delegation ID/target; contains no complete task text |
| `session.thinking.append` | Quiet backend progress, associated delegation ID |
| `session.commentary.append` | Backend outcome to speak; conservative 480-byte content bound |
| `session.output_audio.delta` | Streamed output PCM; no per-response audio-done event |
| `session.close` / `session.closed` | Graceful shutdown |
| `POST /v1/live/sessions/{id}/hangup` | Cleanup fallback |
| `POST /v1/live/sessions` | WebRTC SDP session creation for the existing native app |
| `wss://api.openai.com/v1/live/sessions/{id}/attach` | App server sideband for delegation |

The desktop lab additionally exposes `GET /`, `/client.js`, `/microphone.js`,
`/camera.jpg`, and `WS /voice`. Binary input must be exactly 960 bytes (20 ms);
text `stop` cancels, text `close` ends. Output is PCM binary or JSON ready,
transcript, delegation_result, stop, error. Browser origin must match the host.

## App handoff

Existing backend routes are under `/v1/rooms/{room}/voice`:
`GET /capabilities?device_id=...`, `POST /sessions` with
`device_id`, `sdp`, `codex_enabled`, `request_id`, and `POST /end` with
`device_id`, `session_id`. Existing room-leader requirements remain in place.

Keep WebRTC on the phone and the sideband on the server. Move the tested delegation
runtime behind that sideband with a room-specific executor, persistent notes,
leader lifecycle, and executor ownership. Do not point the simulation backend at
production: it deliberately checks loopback and `execution_domain: simulation`.
The existing app bridge still starts separate Codex runs; this lab's persistent
thread/memory/cancellation behavior has not been rolled out to it.

## What the simulation establishes

The fixture uses the earlier steering-wheel/four-caster base and three-joint arm
with curling tentacle contacts. Ideal depth and visibility-gated simulator labels
are not a SLAM/perception benchmark. It does not validate the new TB6612 two-wheel
base, an unbuilt gripper, torque limits, or physical grasp reliability. Successful
receipts explicitly retain `physical_success: false`.

Approach and collision failures remain valid outcomes; never disable collision
checks or teleport an object to make a voice demo pass. See the benchmark report
for both successes and failures rather than extrapolating reliability from one run.

## Primary references (checked September 2026)

- [GPT-Live 1 model](https://developers.openai.com/api/docs/models/gpt-live-1)
- [Live delegation](https://developers.openai.com/api/docs/guides/live-delegation)
- [Live WebSockets](https://developers.openai.com/api/docs/guides/voice-websockets?api=live)
- [Live prompting](https://developers.openai.com/api/docs/guides/live-prompting)
- [Live server controls](https://developers.openai.com/api/docs/guides/voice-server-controls?api=live)
