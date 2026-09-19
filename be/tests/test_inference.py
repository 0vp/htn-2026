"""GPU scheduling contracts tested without substituting mapping results."""

import asyncio

import pytest

from htn_backend.inference.batching import MicroBatcher


def test_idle_timeout_and_parallel_batches():
    async def check():
        batcher = MicroBatcher(lambda items: [i * 2 for i in items], size=4)
        assert await asyncio.wait_for(batcher.submit(1), 1) == 2
        assert await asyncio.gather(*(batcher.submit(i) for i in range(8))) == [
            i * 2 for i in range(8)
        ]
        assert batcher.stats["largest_batch"] == 4
        assert batcher.pending == 0
        await batcher.close()

    asyncio.run(check())


def test_inference_exception_releases_every_request():
    def process(items):
        raise ValueError("invalid image")

    async def check():
        batcher = MicroBatcher(process)
        with pytest.raises(ValueError, match="invalid image"):
            await asyncio.wait_for(batcher.submit(1), 1)
        assert batcher.pending == 0
        assert batcher.stats["failed"] == 1
        batcher.process = lambda items: items
        assert await batcher.submit(2) == 2
        await batcher.close()

    asyncio.run(check())
