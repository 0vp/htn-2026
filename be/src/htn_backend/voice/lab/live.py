"""Real GPT-Live audio -> persistent Codex -> MuJoCo, with no iPhone or hardware link."""

import argparse
import asyncio
import base64
import json
import os
import time
import wave
from pathlib import Path
from urllib.parse import quote

import httpx
from websockets.asyncio.client import connect

from ...simulation.service import ROOM
from ..prompts import LIVE_INSTRUCTIONS, LIVE_MODEL
from .backend import SimulationBackend
from .runtime import Delegator


class Evidence:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.started = time.monotonic()
        self.events = []

    def __call__(self, event):
        self.events.append({"elapsed_s": round(time.monotonic() - self.started, 3), **event})

    def save(self, outcome):
        self.path.write_text(
            json.dumps(
                {
                    "voice_model": LIVE_MODEL,
                    "backend_model": "gpt-6-astra",
                    "execution_domain": "simulation",
                    "physical_hardware_connected": False,
                    "outcome": outcome,
                    "events": self.events,
                },
                indent=2,
            )
        )


def read_audio(path):
    with wave.open(str(path), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 24000):
            raise ValueError("Input must be mono PCM16 WAV at 24000 Hz")
        if source.getnframes() > 24000 * 60:
            raise ValueError("Input fixture exceeds 60 seconds")
        return source.readframes(source.getnframes())


async def run(url, audio, output, seconds=120):
    if not 5 <= seconds <= 300:
        raise ValueError("Voice test duration must be 5..300 seconds")
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Set OPENAI_API_KEY on the server; never put it in the client")
    pcm = read_audio(audio)
    evidence = Evidence(output)
    backend = SimulationBackend(
        url, ROOM, evidence, Path(output).parent / "voice-sim-memory.sqlite"
    )
    session_id = None
    finalized = False
    generated = bytearray()
    outcome = "failed"
    sender = None
    receiver = None
    runtime = None
    try:
        await backend.start()
        async with connect(
            "wss://api.openai.com/v1/live/sessions",
            additional_headers={"Authorization": f"Bearer {key}"},
            open_timeout=20,
            max_size=4_000_000,
        ) as socket:

            async def send(event):
                await socket.send(json.dumps(event))

            runtime = Delegator(backend, send, evidence)
            await send(
                {
                    "type": "session.start",
                    "event_id": "lab-start",
                    "session": {
                        "model": LIVE_MODEL,
                        "instructions": LIVE_INSTRUCTIONS,
                        "delegation": {"type": "client"},
                        "audio": {
                            "format": {"type": "audio/pcm", "rate": 24000},
                            "output": {"voice": "marin"},
                        },
                    },
                }
            )
            first = json.loads(await asyncio.wait_for(socket.recv(), 25))
            evidence({"kind": "live", **first})
            if first.get("type") != "session.started":
                raise RuntimeError("GPT-Live did not start; inspect evidence")
            session_id = first.get("session", {}).get("id")

            async def stream_audio():
                start = time.monotonic()
                for index in range(int(seconds * 50)):
                    if time.monotonic() - (start + index / 50) > 1:
                        raise RuntimeError("Audio pacing interrupted; refusing a stale burst")
                    # One-second lead-in, then fixture and continuous silence: live-paced PCM.
                    offset = (index - 50) * 960
                    chunk = pcm[offset : offset + 960] if offset >= 0 else b""
                    chunk = chunk.ljust(960, b"\0")
                    await send(
                        {
                            "type": "session.input_audio.append",
                            "audio": base64.b64encode(chunk).decode(),
                        }
                    )
                    await asyncio.sleep(max(0, start + (index + 1) / 50 - time.monotonic()))
                await runtime.close()
                await send({"type": "session.close", "event_id": "lab-close"})

            sender = asyncio.create_task(stream_audio())

            async def receive():
                nonlocal finalized
                async for raw in socket:
                    event = json.loads(raw)
                    kind = event.get("type")
                    if kind == "session.output_audio.delta":
                        generated.extend(base64.b64decode(event["delta"]))
                        continue
                    evidence({"kind": "live", **event})
                    if kind == "error":
                        raise RuntimeError("GPT-Live reported an error; inspect evidence")
                    await runtime.handle(event)
                    if kind == "session.closed":
                        finalized = True
                        break

            receiver = asyncio.create_task(receive())
            async with asyncio.timeout(seconds + 25):
                await asyncio.gather(sender, receiver)
            outcome = "closed" if finalized else "unconfirmed_close"
    finally:
        pending = [task for task in (sender, receiver) if task is not None]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for cleanup in ([runtime.close] if runtime else []) + [backend.close]:
            try:
                await cleanup()
            except Exception as error:
                evidence({"kind": "cleanup_error", "error": type(error).__name__})
        if session_id and not finalized:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.post(
                        "https://api.openai.com/v1/live/sessions/"
                        f"{quote(session_id, safe='')}/hangup",
                        headers={"Authorization": f"Bearer {key}"},
                    )
                    evidence({"kind": "cleanup", "hangup_status": response.status_code})
            except Exception as error:
                evidence({"kind": "cleanup_error", "error": type(error).__name__})
        with wave.open(str(Path(output).with_suffix(".wav")), "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(24000)
            target.writeframes(generated)
        evidence({"kind": "audio_summary", "output_bytes": len(generated)})
        evidence.save(outcome)
    return evidence.events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--server", default="http://127.0.0.1:8792")
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--output", type=Path, default=Path("/tmp/voice-sim-result.json"))
    args = parser.parse_args()
    asyncio.run(run(args.server, args.audio, args.output, args.seconds))
    print(f"Evidence: {args.output}; assistant audio: {args.output.with_suffix('.wav')}")


if __name__ == "__main__":
    main()
