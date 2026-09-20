"""Client-delegation event loop shared by primary WebSocket and future sideband use."""

import asyncio
import re
import uuid

STOP = re.compile(
    r"^\s*(?:please\s+)?(?:stop(?:\s+(?:now|moving|the robot))?"
    r"|cancel(?:\s+(?:that|the task))?)[.!?\s]*$",
    re.I,
)


class Delegator:
    def __init__(self, backend, send, record=lambda event: None):
        self.backend, self.send, self.record = backend, send, record
        self.history, self.results = [], []
        self.seen, self.event_ids = set(), set()
        self.worker = None
        self.generation = 0
        self.input_version = 0
        self.last_delegated_version = -1
        self.interrupted_version = -1
        self.closed = False

    async def append(self, kind, ident, content):
        # Bound by UTF-8 bytes as a conservative <=500 token payload, including Unicode.
        content = content.encode()[:480].decode(errors="ignore")
        event = {
            "type": kind,
            "event_id": uuid.uuid4().hex,
            "delegation_id": ident,
            "content": content,
        }
        await self.send(event)
        self.record({"kind": "append", **event})

    async def interrupt(self):
        self.interrupted_version = self.input_version
        self.generation += 1
        if self.worker and not self.worker.done():
            self.worker.cancel()
        # Stop the executor as well as cancelling reasoning. Do not wait for Codex first.
        try:
            receipt = await self.backend.stop()
        finally:
            if self.worker:
                await asyncio.gather(self.worker, return_exceptions=True)
            self.worker = None
        return receipt

    async def stop_requested(self):
        receipt = await self.interrupt()
        await self.append(
            "session.commentary.append",
            None,
            "Simulation stop confirmed."
            if receipt.get("simulation_success") is True
            else "Stop requested; stopping has not been confirmed.",
        )
        return receipt

    async def handle(self, event):
        if self.closed:
            return
        ident = event.get("event_id")
        if ident and ident in self.event_ids:
            return
        if ident:
            self.event_ids.add(ident)
        kind = event.get("type")
        if kind in {"session.input_transcript.delta", "session.output_transcript.delta"}:
            role = "user" if kind == "session.input_transcript.delta" else "assistant"
            delta = str(event.get("delta", ""))
            if self.history and self.history[-1]["role"] == role:
                self.history[-1]["text"] = (self.history[-1]["text"] + delta)[-8000:]
            else:
                self.history.append({"role": role, "text": delta[-8000:]})
            self.history = self.history[-40:]
            if role == "user":
                self.input_version += 1
                if STOP.fullmatch(delta) or STOP.fullmatch(self.history[-1]["text"]):
                    await self.stop_requested()
        elif kind == "session.delegation.created":
            delegation = event["delegation"]
            ident = delegation["id"]
            if ident in self.seen or delegation.get("target", "client") != "client":
                return
            self.seen.add(ident)
            if not any(h["role"] == "user" and h["text"].strip() for h in self.history):
                await self.append(
                    "session.commentary.append",
                    ident,
                    "No usable user transcript arrived. Please repeat the request.",
                )
                return
            if self.input_version in {self.last_delegated_version, self.interrupted_version}:
                await self.append(
                    "session.thinking.append",
                    ident,
                    "This user input was already handled. Do not repeat the action.",
                )
                return
            if self.worker and not self.worker.done():
                await self.interrupt()
            self.last_delegated_version = self.input_version
            self.generation += 1
            generation = self.generation
            context = {
                "conversation": [dict(h) for h in self.history],
                "prior_results": self.results[-8:],
                "execution_domain": "simulation",
            }
            self.worker = asyncio.create_task(self.work(ident, context, generation))
        elif kind == "session.closed":
            await self.close()

    async def work(self, ident, context, generation):
        try:
            await self.append(
                "session.thinking.append",
                ident,
                "Codex is checking the simulation. No completion is confirmed yet.",
            )
            result = await self.backend.ask(context)
            if generation != self.generation:
                return
            self.results.append({"delegation_id": ident, "result": result[-4000:]})
            await self.append(
                "session.commentary.append", ident, result or "No confirmed result was returned."
            )
            self.record({"kind": "delegation_result", "id": ident, "result": result})
        except asyncio.CancelledError:
            raise
        except Exception as error:
            try:
                await self.backend.stop()
            except Exception as stop_error:
                self.record({"kind": "stop_error", "error": type(stop_error).__name__})
            self.record({"kind": "backend_error", "error": type(error).__name__})
            await self.append(
                "session.commentary.append",
                ident,
                "The task failed. No successful completion is confirmed.",
            )

    async def close(self):
        if not self.closed:
            self.closed = True
            await self.interrupt()
