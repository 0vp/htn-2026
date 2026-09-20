import asyncio

import pytest

from htn_backend.voice.lab.backend import SimulationBackend
from htn_backend.voice.lab.runtime import Delegator


class Backend:
    def __init__(self):
        self.calls, self.stops = [], 0
        self.gate = None

    async def ask(self, context):
        self.calls.append(context)
        if self.gate:
            await self.gate.wait()
        return "The simulated block is on the table."

    async def stop(self):
        self.stops += 1
        return {"simulation_success": True}


def test_deltas_duplicates_and_memory():
    async def exercise():
        sent = []

        async def send(event):
            sent.append(event)

        backend = Backend()
        runtime = Delegator(backend, send)
        for delta in ("Find the ", "blue block."):
            await runtime.handle({"type": "session.input_transcript.delta", "delta": delta})
        event = {"type": "session.delegation.created", "delegation": {"id": "one"}}
        await runtime.handle(event)
        await runtime.worker
        await runtime.handle(event)
        await runtime.handle({"type": "session.delegation.created", "delegation": {"id": "two"}})
        assert len(backend.calls) == 1
        assert backend.calls[0]["conversation"][0]["text"] == "Find the blue block."
        await runtime.handle({"type": "session.output_transcript.delta", "delta": "Found it."})
        await runtime.handle({"type": "session.input_transcript.delta", "delta": "Where is it?"})
        await runtime.handle({"type": "session.delegation.created", "delegation": {"id": "three"}})
        await runtime.worker
        assert backend.calls[-1]["prior_results"][0]["delegation_id"] == "one"
        assert sent[-1]["delegation_id"] == "three"
        await runtime.close()

    asyncio.run(exercise())


def test_stop_interrupts_work_and_suppresses_late_result():
    async def exercise():
        sent = []

        async def send(event):
            sent.append(event)

        backend = Backend()
        backend.gate = asyncio.Event()
        runtime = Delegator(backend, send)
        await runtime.handle({"type": "session.input_transcript.delta", "delta": "Pick it up."})
        await runtime.handle({"type": "session.delegation.created", "delegation": {"id": "one"}})
        await asyncio.sleep(0)
        await runtime.handle({"type": "session.input_transcript.delta", "delta": "Stop!"})
        assert backend.stops == 1
        assert runtime.worker is None
        assert not runtime.results
        assert sent[-1]["content"] == "Simulation stop confirmed."
        await runtime.handle({"type": "session.delegation.created", "delegation": {"id": "two"}})
        assert len(backend.calls) == 1

    asyncio.run(exercise())


def test_missing_transcript_never_dispatches():
    async def exercise():
        backend = Backend()
        sent = []

        async def send(event):
            sent.append(event)

        runtime = Delegator(backend, send)
        await runtime.handle({"type": "session.delegation.created", "delegation": {"id": "empty"}})
        assert not backend.calls
        assert "repeat" in sent[-1]["content"]
        await runtime.append("session.thinking.append", None, "机器人" * 500)
        assert len(sent[-1]["content"].encode()) <= 480

    asyncio.run(exercise())


@pytest.mark.parametrize("url", ["https://robot.example", "http://192.168.4.1", "file:///tmp"])
def test_no_physical_endpoint(url):
    with pytest.raises(ValueError):
        SimulationBackend(url, "51A00001")


def test_failure_stops_executor_even_when_stop_receipt_fails():
    async def exercise():
        class Broken(Backend):
            async def ask(self, context):
                raise TimeoutError("backend")

            async def stop(self):
                self.stops += 1
                raise ConnectionError("executor unavailable")

        backend, sent = Broken(), []

        async def send(event):
            sent.append(event)

        runtime = Delegator(backend, send)
        await runtime.handle({"type": "session.input_transcript.delta", "delta": "Pick it up."})
        await runtime.handle({"type": "session.delegation.created", "delegation": {"id": "one"}})
        await runtime.worker
        assert backend.stops == 1
        assert "No successful completion" in sent[-1]["content"]
        assert not runtime.results

    asyncio.run(exercise())


def test_shutdown_idempotent_and_ignores_later_delegation():
    async def exercise():
        backend = Backend()

        async def send(event):
            pass

        runtime = Delegator(backend, send)
        await runtime.close()
        await runtime.close()
        await runtime.handle({"type": "session.input_transcript.delta", "delta": "Pick it up."})
        await runtime.handle({"type": "session.delegation.created", "delegation": {"id": "late"}})
        assert backend.stops == 1
        assert not backend.calls

    asyncio.run(exercise())


def test_new_request_preempts_old_task_and_only_reports_new_result():
    async def exercise():
        backend, sent = Backend(), []
        backend.gate = asyncio.Event()

        async def send(event):
            sent.append(event)

        runtime = Delegator(backend, send)
        await runtime.handle({"type": "session.input_transcript.delta", "delta": "Pick it up."})
        await runtime.handle({"type": "session.delegation.created", "delegation": {"id": "old"}})
        await asyncio.sleep(0)
        await runtime.handle({"type": "session.output_transcript.delta", "delta": "Checking."})
        await runtime.handle(
            {"type": "session.input_transcript.delta", "delta": "Look around instead."}
        )
        await runtime.handle({"type": "session.delegation.created", "delegation": {"id": "new"}})
        backend.gate.set()
        await runtime.worker
        assert backend.stops == 1
        assert [r["delegation_id"] for r in runtime.results] == ["new"]
        assert backend.calls[-1]["conversation"][-1]["text"] == "Look around instead."

    asyncio.run(exercise())
