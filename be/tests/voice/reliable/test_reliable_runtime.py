import asyncio
from types import SimpleNamespace

import numpy as np

from htn_backend.voice.reliable import runtime
from htn_backend.voice.reliable.journal import Journal
from htn_backend.voice.reliable.transcribe import Utterance


def test_no_sample_loss_at_boundaries():
    window = Utterance()
    speech = np.full(4800, 1000, dtype="<i2").tobytes()
    chunks = [bytes(9600)] * 3 + [speech] * 5 + [bytes(9600)] * 5
    for seq, chunk in enumerate(chunks):
        ready = window.add(seq, chunk)
        assert ready == (seq == len(chunks) - 1)
    first, recovered = window.take()
    assert first == 0
    assert recovered == b"".join(chunks)


def test_final_only_execution_and_no_replay(tmp_path, monkeypatch):
    async def scenario():
        journal = Journal(tmp_path / "audio.sqlite")
        journal.create("one", "room", "phone", "request", True)
        journal.finalize("one", 0, 1, "pick up", "fragment")
        journal.finalize("one", 2, 3, "the blue bottle")
        calls = []

        async def run(room, text, base=None, binary=None, motion=None, progress=None):
            calls.append(text)
            return "confirmed result"

        monkeypatch.setattr(runtime, "run", run)
        monkeypatch.setattr(runtime, "DELEGATION_WAIT_S", 0)
        service = SimpleNamespace(key=lambda: "test", client=None)
        for _ in range(2):
            worker = runtime.Runtime(service, journal, "one")
            worker.ending = True
            done = asyncio.create_task(asyncio.sleep(0))
            await done
            worker.tasks = [done, done]
            await worker.actions()
        assert calls == ["Finalized user speech:\npick up the blue bottle"]
        assert journal.snapshot("one")[-1]["result"] == "confirmed result"
        journal.close()

    asyncio.run(scenario())


def test_final_partial_chunk_preserves_journal(tmp_path, monkeypatch):
    async def scenario():
        journal = Journal(tmp_path / "audio.sqlite")
        journal.create("one", "room", "phone", "request", False)
        pcm = np.full(3200, 1000, dtype="<i2").tobytes()
        journal.append("one", 0, pcm)
        received = []

        async def transcribe(client, key, data):
            received.append(data)
            return "complete short utterance"

        monkeypatch.setattr(runtime, "transcribe", transcribe)
        worker = runtime.Runtime(SimpleNamespace(key=lambda: "test", client=None), journal, "one")
        worker.ending = True
        await worker.transcription()
        assert received == [pcm]
        assert journal.completed("one") == 1
        assert journal.chunk("one", 0) == pcm
        journal.close()

    asyncio.run(scenario())


def test_cancelled_command_is_not_replayed(tmp_path, monkeypatch):
    async def scenario():
        journal = Journal(tmp_path / "cancel.sqlite")
        journal.create("one", "room", "phone", "request", True)
        journal.finalize("one", 0, 0, "go to the door")
        started = asyncio.Event()

        async def run(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(runtime, "run", run)
        monkeypatch.setattr(runtime, "DELEGATION_WAIT_S", 0)
        worker = runtime.Runtime(SimpleNamespace(key=lambda: "test", client=None), journal, "one")
        task = asyncio.create_task(worker.actions())
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert journal.snapshot("one")[0]["action"] == "unknown"
        assert not journal.claim("one", 0)
        journal.close()

    asyncio.run(scenario())


def test_chatter_is_ignored_but_delegated_speech_runs(tmp_path, monkeypatch):
    async def scenario():
        journal = Journal(tmp_path / "gate.sqlite")
        journal.create("one", "room", "phone", "request", True)
        journal.finalize("one", 0, 0, "Okay, I'm on it.")  # The robot hearing its own voice.
        journal.finalize("one", 1, 1, "Is he an elite hitter?")  # Live voice delegated this one.
        calls = []

        async def run(room, text, **_):
            calls.append(text)
            return "done"

        monkeypatch.setattr(runtime, "run", run)
        monkeypatch.setattr(runtime, "DELEGATION_WAIT_S", 0)
        worker = runtime.Runtime(SimpleNamespace(key=lambda: "test", client=None), journal, "one")
        task = asyncio.create_task(worker.actions())
        await asyncio.sleep(0.3)
        assert calls == [] and journal.snapshot("one")[0]["action"] == "ignored"
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
