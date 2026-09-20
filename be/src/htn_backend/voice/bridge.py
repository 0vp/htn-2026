"""Live event bridge. Audio stays on the phone's WebRTC connection."""

import asyncio
import json
import shutil
from urllib.parse import quote

from websockets.asyncio.client import connect

from ..agent import remote


async def run(room_id, prompt, backend=None, binary=None, motion=None, progress=None):
    """Laptop worker when one is polling, else the server's own Codex (see agent/remote.py)."""
    return await remote.execute(room_id, prompt, progress)


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
        history, last_role = [], None
        seen = set()
        jobs = set()
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

        async def work(ident, context):
            """One delegated request. A newer one interrupts it on the worker (newest wins)."""

            async def progress(text):
                await say(ident, text)

            try:
                result = await run(
                    room_id,
                    "Live voice conversation so far (transcripts can contain mistakes). Act on "
                    "the user's latest request.\n" + context,
                    progress=progress,
                )
                if result:  # Empty: a newer request took over and will answer instead.
                    await say(ident, result)
            except asyncio.CancelledError:
                raise
            except Exception:
                await say(ident, "Something went wrong on my side. Ask me again.")

        try:
            async for raw in socket:
                event = json.loads(raw)
                kind = event.get("type")
                if kind in {"session.input_transcript.delta", "session.output_transcript.delta"}:
                    role = "\nUser: " if kind == "session.input_transcript.delta" else "\nKevin: "
                    if last_role != role:
                        history.append(role)
                    last_role = role
                    history.append(event.get("delta", ""))
                    history = history[-400:]
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
                    else:
                        job = asyncio.create_task(work(ident, "".join(history)[-6000:]))
                        jobs.add(job)
                        job.add_done_callback(jobs.discard)
                elif kind == "session.closed":
                    return
        finally:
            for job in tuple(jobs):
                job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
