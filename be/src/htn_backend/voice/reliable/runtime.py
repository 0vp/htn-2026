"""Independent durable ingestion, transcription, and conversational playback."""

import asyncio
import base64
import json
import os
import time

from websockets.asyncio.client import connect

from ...agent.motion.shared import server_motion
from ...agent.run import run
from ..bridge import codex_binary
from .transcribe import Utterance, transcribe


class Runtime:
    def __init__(self, service, journal, ident):
        self.service, self.journal, self.ident = service, journal, ident
        self.room, self.device, self.codex, _ = journal.session(ident)
        for turn in journal.snapshot(ident):
            if turn["action"] == "running":
                journal.result(
                    ident,
                    int(turn["id"]),
                    "Previous execution was interrupted; outcome is unconfirmed.",
                    "unknown",
                )
        self.browser = None
        self.send_lock = asyncio.Lock()
        self.deadline = time.monotonic() + 1800
        self.tasks = []
        self.ready = False
        self.ending = False
        self.failed = False
        self.upstream = None

    async def emit(self, event):
        async with self.send_lock:
            if self.browser:
                try:
                    await self.browser.send_json(event)
                except Exception:
                    self.browser = None

    def start(self):
        if self.tasks and self.failed:
            for task in self.tasks:
                task.cancel()
            self.tasks = []
            self.failed = False
            self.ending = False
        if not self.tasks:
            self.tasks = [
                asyncio.create_task(self.guarded(fn))
                for fn in (self.conversation, self.transcription, self.actions)
            ]

    async def guarded(self, fn):
        try:
            await fn()
        except asyncio.CancelledError:
            raise
        except Exception:
            self.failed = True
            await self.emit(
                {
                    "type": "status",
                    "text": "Audio is saved; processing interrupted. Reconnect to retry.",
                }
            )

    async def conversation(self):
        # This stream supplies conversational audio only. Its provisional text NEVER
        # enters Codex. Provider audio appends have no per-chunk acknowledgment.
        async with (
            asyncio.timeout(max(1, self.deadline - time.monotonic())),
            connect(
                "wss://api.openai.com/v1/live/sessions",
                additional_headers={"Authorization": f"Bearer {self.service.key()}"},
                max_size=4_000_000,
                open_timeout=20,
            ) as upstream,
        ):
            await upstream.send(
                json.dumps(
                    {
                        "type": "session.start",
                        "session": {
                            "model": "gpt-live-1",
                            "delegation": {"type": "client"},
                            "instructions": "Be concise. You are a room assistant. "
                            "A separate reliable transcription worker handles Codex requests. "
                            "Do not claim to execute actions or confirm their completion yourself.",
                            "audio": {
                                "format": {"type": "audio/pcm", "rate": 24000},
                                "output": {"voice": "marin"},
                            },
                        },
                    }
                )
            )
            started = json.loads(await asyncio.wait_for(upstream.recv(), 25))
            if started.get("type") != "session.started":
                raise RuntimeError("Voice provider did not start")
            self.upstream = upstream
            self.ready = True
            await self.emit({"type": "ready"})

            async def feed():
                seq = await asyncio.to_thread(self.journal.completed, self.ident)
                due = time.monotonic()
                while time.monotonic() < self.deadline and not self.ending:
                    pcm = await asyncio.to_thread(self.journal.chunk, self.ident, seq)
                    if pcm is None:
                        due = time.monotonic()
                        await asyncio.sleep(0.04)
                        continue
                    await upstream.send(
                        json.dumps(
                            {
                                "type": "session.input_audio.append",
                                "audio": base64.b64encode(pcm).decode(),
                            }
                        )
                    )
                    seq += 1
                    # Replay recorded timing, never burst an outage backlog into Live.
                    due += len(pcm) / 48000
                    await asyncio.sleep(max(0, due - time.monotonic()))

            feeder = asyncio.create_task(feed())
            try:
                async for raw in upstream:
                    event = json.loads(raw)
                    kind = event.get("type")
                    if kind in {"session.output_audio.delta", "session.output_transcript.delta"}:
                        await self.emit(event)
                    elif kind == "session.delegation.created":
                        await upstream.send(
                            json.dumps(
                                {
                                    "type": "session.commentary.append",
                                    "delegation_id": event["delegation"]["id"],
                                    "content": "Wait for finalized speech before executing.",
                                }
                            )
                        )
                    elif kind in {"error", "session.error"}:
                        raise RuntimeError("Voice provider error")
            finally:
                self.upstream = None
                self.ready = False
                feeder.cancel()
                await asyncio.gather(feeder, return_exceptions=True)
                try:
                    await upstream.send(json.dumps({"type": "session.close"}))
                except Exception:
                    pass

    async def transcription(self):
        seq = await asyncio.to_thread(self.journal.completed, self.ident)
        window = Utterance()
        while time.monotonic() < self.deadline:
            pcm = await asyncio.to_thread(self.journal.chunk, self.ident, seq)
            if pcm is None:
                if self.ending and window.parts:
                    await self.finish_window(window, seq - 1)
                if self.ending:
                    await asyncio.to_thread(self.journal.seal_tail, self.ident)
                    return
                await asyncio.sleep(0.05)
                continue
            if window.add(seq, pcm):
                await self.finish_window(window, seq)
            seq += 1

    async def finish_window(self, window, last):
        boundary = window.quiet >= 24000 or self.ending
        speech = window.speech
        first, pcm = window.take()
        # Recover soft opening syllables from the preceding quiet window. This is
        # inference context, not extra ingestion or a second command.
        prefix = b""
        previous = await asyncio.to_thread(self.journal.snapshot, self.ident)
        if speech and (not previous or not previous[-1]["text"]):
            seq = first - 1
            while seq >= 0 and len(prefix) < 24000:
                prefix = (
                    await asyncio.to_thread(self.journal.chunk, self.ident, seq) or b""
                ) + prefix
                seq -= 1
            pcm = prefix[-24000:] + pcm
        # Retry the same complete waveform. Never commit a partial failed result.
        for attempt in range(6):
            try:
                text = (
                    await transcribe(self.service.client, self.service.key(), pcm) if speech else ""
                )
                await asyncio.to_thread(
                    self.journal.finalize,
                    self.ident,
                    first,
                    last,
                    text,
                    "pending" if boundary else "fragment",
                )
                await self.emit(
                    {
                        "type": "final",
                        "turns": await asyncio.to_thread(self.journal.snapshot, self.ident),
                    }
                )
                return
            except Exception:
                await self.emit(
                    {
                        "type": "status",
                        "text": "Audio saved. Retrying complete-utterance transcription…",
                    }
                )
                await asyncio.sleep(min(2**attempt, 15))
        raise RuntimeError("Transcription unavailable; retained audio requires retry")

    async def actions(self):
        while time.monotonic() < self.deadline:
            turns = await asyncio.to_thread(self.journal.snapshot, self.ident)
            fragments = []
            for turn in turns:
                if turn["action"] == "fragment":
                    fragments.append(turn["text"])
                    continue
                command = " ".join([*fragments, turn["text"]]).strip()
                fragments = []
                if not self.codex or not command or turn["action"] != "pending":
                    continue
                first = int(turn["id"])
                if not await asyncio.to_thread(self.journal.claim, self.ident, first):
                    continue
                try:
                    result = await run(
                        self.room,
                        "Finalized user speech:\n" + command,
                        os.environ.get("HTN_SERVER_URL", "http://127.0.0.1:8790"),
                        codex_binary(),
                        server_motion(),
                    )
                    await asyncio.to_thread(self.journal.result, self.ident, first, result)
                    if self.upstream:
                        try:
                            await self.upstream.send(
                                json.dumps(
                                    {
                                        "type": "session.commentary.append",
                                        "delegation_id": None,
                                        "content": (
                                            result or "Task finished without a confirmed result."
                                        )[:1200],
                                    }
                                )
                            )
                        except Exception:
                            pass  # Stored result still appears in the final transcript snapshot.
                except asyncio.CancelledError:
                    await asyncio.to_thread(
                        self.journal.result,
                        self.ident,
                        first,
                        "Execution interrupted; outcome unconfirmed.",
                        "unknown",
                    )
                    raise
                except Exception:
                    await asyncio.to_thread(
                        self.journal.result,
                        self.ident,
                        first,
                        "Execution outcome unconfirmed; not automatically retried.",
                        "unknown",
                    )
                await self.emit(
                    {
                        "type": "final",
                        "turns": await asyncio.to_thread(self.journal.snapshot, self.ident),
                    }
                )
            if self.ending and self.tasks[1].done():
                return
            await asyncio.sleep(0.1)

    async def close(self):
        self.ending = True
        # Ingestion is closed first; finishing includes the final short utterance.
        if self.tasks:
            self.tasks[0].cancel()
        if self.tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*self.tasks[1:]), 120)
            except Exception:
                pass
            for task in self.tasks:
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
