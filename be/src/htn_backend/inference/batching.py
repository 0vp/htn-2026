"""Bounded FIFO microbatch execution with per-request results and cancellation."""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class Request:
    value: Any
    future: asyncio.Future
    queued_at: float


class MicroBatcher:
    """One GPU execution stream; independently queued callers share short batches."""

    def __init__(self, process: Callable, size: int = 4, delay_s: float = 0.002):
        self.process = process
        self.size = size
        self.delay_s = delay_s
        self.queue = asyncio.Queue(maxsize=16)
        self.task = None
        self.closing = False
        self.pending = 0
        self.stats = dict(batches=0, images=0, largest_batch=0, failed=0)

    async def submit(self, value: Any) -> Any:
        if self.closing:
            raise RuntimeError("inference worker is closing")
        if self.pending >= 16:
            raise OverflowError("inference queue full")
        if self.task is None:
            self.task = asyncio.create_task(self._run())
        future = asyncio.get_running_loop().create_future()
        self.pending += 1
        self.queue.put_nowait(Request(value, future, time.monotonic()))
        return await future

    async def _run(self):
        while True:
            first = await self.queue.get()
            group = [first]
            deadline = first.queued_at + self.delay_s
            while len(group) < self.size:
                try:
                    group.append(self.queue.get_nowait())
                    continue
                except asyncio.QueueEmpty:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or self.closing:
                        break
                try:
                    group.append(await asyncio.wait_for(self.queue.get(), remaining))
                except asyncio.TimeoutError:  # noqa: UP041 - CUDA runtime also supports Python 3.10
                    break
            live = []
            for request in group:
                if request.future.done():
                    continue
                if time.monotonic() - request.queued_at > 3:
                    request.future.set_exception(TimeoutError("inference queue timeout"))
                else:
                    live.append(request)
            try:
                if live:
                    # CPU preparation happens before submission; only this call owns the model.
                    results = await asyncio.to_thread(self.process, [r.value for r in live])
                    if len(results) != len(live):
                        raise RuntimeError("inference batch result count mismatch")
                    for request, result in zip(live, results, strict=True):
                        if not request.future.done():
                            request.future.set_result(result)
                    self.stats["batches"] += 1
                    self.stats["images"] += len(live)
                    self.stats["largest_batch"] = max(self.stats["largest_batch"], len(live))
            except Exception as error:
                self.stats["failed"] += len(live)
                for request in live:
                    if not request.future.done():
                        request.future.set_exception(error)
            finally:
                for _ in group:
                    self.pending -= 1
                    self.queue.task_done()

    async def close(self):
        self.closing = True
        await self.queue.join()
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
