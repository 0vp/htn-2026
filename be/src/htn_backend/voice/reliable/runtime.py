"""Independent durable ingestion, transcription, and conversational playback."""

import asyncio
import base64
import json
import re
import time

from websockets.asyncio.client import connect

from ...agent import remote
from .transcribe import Utterance, transcribe


async def run(room_id, prompt, backend=None, binary=None, motion=None, progress=None):
    """Laptop worker when one is polling, else the server's own Codex (see agent/remote.py)."""
    return await remote.execute(room_id, prompt, progress)


LIVE_INSTRUCTIONS = """# Role
You are Astra, the voice of a small two-wheeled robot rolling around a hackathon. You are
curious, upbeat and a little cheeky, like a friendly droid. Speak English only, in short
natural sentences. Never read lists or markdown aloud.

# Backend
A backend agent is your body and eyes: it sees through the robot's camera and LiDAR, drives,
turns, explores, finds things, dances, and remembers the room. You cannot see or move without it.

# Delegate to the backend when
- The user asks you to move, go, come, follow, turn, spin, dance, stop, explore, or find anything.
- The user asks what you see, where something is, or anything about the room or the robot.
- The user follows up on, corrects or cancels a task in progress.
Delegate before answering anything that depends on the backend. Never guess what it will find.
When you delegate, acknowledge in three to six playful words ("On it, rolling out!").

# Do not delegate when
- It is small talk, jokes, or questions about you: answer yourself, in character.
- The speech is not addressed to you: nearby conversations, people talking to each other, other
  languages in the background, music, or your own voice echoing. Stay silent and keep listening.

# Commentary
Progress and results arrive as commentary while the backend works. Say each one aloud right
away in your own lively words, one short sentence, keeping every fact. Never add facts that
were not in the commentary, and never claim a result before commentary reports it.
"""

# Safety net for requests the live voice failed to delegate: the robot's name plus an action
# word, or a bare stop. Anything looser lets table talk ("did you see the game") drive the robot.
WAKE_WORDS = re.compile(r"\b(robot|astra)\b", re.IGNORECASE)
ACTION_WORDS = re.compile(
    r"\b(go|move|drive|come|follow|turn|spin|twirl|dance|scan|explore|find|look|search|where|"
    r"see|back|forward|left|right|pick|grab|bring|take|get|put|push|check|status|show)\b",
    re.IGNORECASE,
)
STOP_WORDS = re.compile(r"^\W*(stop|halt|freeze)\b", re.IGNORECASE)


def is_command(text: str) -> bool:
    if STOP_WORDS.search(text):
        return True
    return bool(WAKE_WORDS.search(text) and ACTION_WORDS.search(text))


DELEGATION_FRESH_S = 25.0
DELEGATION_WAIT_S = 3.0


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
        self.delegations = []  # [id, received_at] not yet matched to a finalized utterance
        self.delegation = None  # The one the running agent turn answers.
        self.jobs = set()

    async def say(self, text):
        """Progress from the working agent: shown on the phone and spoken by the live voice."""
        await self.emit({"type": "status", "text": text[:200]})
        if self.upstream:
            try:
                await self.upstream.send(
                    json.dumps(
                        {
                            "type": "session.commentary.append",
                            "delegation_id": self.delegation,
                            "content": text[:400],
                        }
                    )
                )
            except Exception:
                pass

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
                            "instructions": LIVE_INSTRUCTIONS,
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
                        # The live voice decided someone asked the robot for something.
                        self.delegations.append([event["delegation"]["id"], time.monotonic()])
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

    async def addressed(self, command):
        """Delegation id (or None) when this utterance is a request to the robot, else False.

        The live voice hears tone and turn-taking, so its decision to delegate is the main
        signal; command words are the safety net for requests it failed to delegate.
        """
        deadline = time.monotonic() + DELEGATION_WAIT_S
        while True:
            now = time.monotonic()
            self.delegations = [d for d in self.delegations if now - d[1] <= DELEGATION_FRESH_S]
            if self.delegations:
                return self.delegations.pop(0)[0]
            if now >= deadline:
                return None if is_command(command) else False
            await asyncio.sleep(0.1)

    async def actions(self):
        try:
            await self.dispatch()
        finally:
            for job in tuple(self.jobs):
                job.cancel()
            await asyncio.gather(*self.jobs, return_exceptions=True)

    async def dispatch(self):
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
                delegation = await self.addressed(command)
                if delegation is False:
                    # Chatter, echo of our own voice, or talk between people: not for the robot.
                    await asyncio.to_thread(self.journal.result, self.ident, first, "", "ignored")
                    continue
                # Run in the background so a newer request can interrupt this one: the worker
                # stops the older turn when the next arrives, like a person being spoken to.
                job = asyncio.create_task(self.execute(first, command, delegation))
                self.jobs.add(job)
                job.add_done_callback(self.jobs.discard)
            if self.ending and self.tasks[1].done():
                await asyncio.gather(*self.jobs, return_exceptions=True)
                return
            await asyncio.sleep(0.1)

    async def execute(self, first, command, delegation):
        async def progress(text):
            self.delegation = delegation
            await self.say(text)

        try:
            result = await run(self.room, "Finalized user speech:\n" + command, progress=progress)
            await asyncio.to_thread(self.journal.result, self.ident, first, result)
            if result:  # Empty: a newer request took over and will answer instead.
                await progress(result[:1200])
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
            {"type": "final", "turns": await asyncio.to_thread(self.journal.snapshot, self.ident)}
        )

    async def close(self):
        self.ending = True
        for job in tuple(self.jobs):
            job.cancel()
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
