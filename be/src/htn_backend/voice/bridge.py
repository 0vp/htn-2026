"""Live event bridge. Audio stays on the phone's WebRTC connection."""

import asyncio
import json
import shutil
from urllib.parse import quote

from websockets.asyncio.client import connect

from ..agent import remote


async def run(room_id, prompt, backend=None, binary=None, motion=None):
    """Laptop worker when one is polling, else the server's own Codex (see agent/remote.py)."""
    return await remote.execute(room_id, prompt)


def codex_binary():
    return shutil.which("codex")


async def bridge(session_id, key, room_id, enabled, ready):
    url = f"wss://api.openai.com/v1/live/sessions/{quote(session_id, safe='')}/attach"
    async with connect(
        url,
        additional_headers={"Authorization": f"Bearer {key}"},
        max_size=4_000_000,
        open_timeout=15,
    ) as socket:
        history = []
        seen = set()
        tasks = asyncio.Queue(maxsize=4)
        ready.set()

        async def say(ident, text):
            await socket.send(
                json.dumps(
                    {
                        "type": "session.commentary.append",
                        "delegation_id": ident,
                        "content": text[:1600],
                    }
                )
            )

        async def work():
            while True:
                ident, context = await tasks.get()
                try:
                    result = await run(
                        room_id,
                        "Voice conversation context (transcripts may be incomplete). "
                        "Answer the latest request using room evidence; ask if unclear.\n"
                        + context,
                    )
                    await say(ident, result or "The task finished without a confirmed result.")
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await say(
                        ident, "Codex could not complete the request. No result is confirmed."
                    )
                finally:
                    tasks.task_done()

        worker = asyncio.create_task(work())
        try:
            async for raw in socket:
                event = json.loads(raw)
                kind = event.get("type")
                if kind in {"session.input_transcript.delta", "session.output_transcript.delta"}:
                    role = "User" if kind == "session.input_transcript.delta" else "Assistant"
                    history.append(f"{role}: {event.get('delta', '')}")
                    history = history[-160:]
                elif kind == "session.delegation.created":
                    ident = event["delegation"]["id"]
                    if ident in seen:
                        continue
                    seen.add(ident)
                    if not enabled:
                        await say(
                            ident,
                            "Conversation-only mode: Codex and room tools are disconnected. "
                            "Do not claim to inspect the room or perform actions.",
                        )
                    elif tasks.full():
                        await say(
                            ident,
                            "There are already several requests waiting. Please wait for a result.",
                        )
                    else:
                        tasks.put_nowait((ident, "\n".join(history)[-16000:]))
                elif kind == "session.closed":
                    return
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
