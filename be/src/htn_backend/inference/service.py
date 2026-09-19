"""Private image inference API with CPU preparation and bounded GPU microbatches."""

import base64
import hmac
import threading
import time
from contextlib import asynccontextmanager

import anyio
import numpy as np
from fastapi import FastAPI, Header, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .batching import MicroBatcher
from .wire import decode_image


def create_app(model, secret: str, features=None) -> FastAPI:
    if len(secret) < 24:
        raise ValueError("GPU token must be at least 24 characters")
    gpu_lock = threading.Lock()
    admission = anyio.CapacityLimiter(16)
    preparation = anyio.CapacityLimiter(2)

    def process(prepared):
        began = time.perf_counter()
        with gpu_lock:
            results = model.batch(prepared)
        elapsed = (time.perf_counter() - began) * 1000
        return [
            dict(
                detections=[
                    dict(
                        label=item.label,
                        score=item.score,
                        mask=base64.b64encode(np.packbits(item.mask).tobytes()).decode(),
                    )
                    for item in detections[:128]
                ],
                mask_shape=list(item[0].depth.shape),
                inference_ms=elapsed,
                batch_size=len(prepared),
            )
            for item, detections in zip(prepared, results, strict=True)
        ]

    # Queueing behind an active batch already coalesces requests; don't delay an idle GPU.
    worker = MicroBatcher(process, delay_s=0)

    @asynccontextmanager
    async def lifespan(app):
        yield
        for batcher in app.state.workers:
            await batcher.close()

    app = FastAPI(lifespan=lifespan)
    app.state.batcher = worker
    app.state.workers = [worker]

    def authorize(authorization):
        if not hmac.compare_digest(authorization, f"Bearer {secret}"):
            raise HTTPException(401, "invalid token")

    @app.get("/health")
    async def health(authorization: str = Header(default="")):
        authorize(authorization)
        result = dict(status="ready", pending=worker.pending, **worker.stats)
        if len(app.state.workers) > 1:
            result["feature_extraction"] = dict(app.state.workers[1].stats)
            result["feature_matching"] = dict(app.state.workers[2].stats)
        return result

    @app.post("/detect")
    async def detect(request: Request, authorization: str = Header(default="")):
        authorize(authorization)
        try:
            admission.acquire_nowait()
        except anyio.WouldBlock as error:
            raise HTTPException(429, "inference queue full") from error
        try:
            payload = await read_payload(request)
            async with preparation:
                prepared = await run_in_threadpool(
                    lambda: model.prepare(decode_image(bytes(payload)))
                )
            began = time.perf_counter()
            result = await worker.submit(prepared)
            result["queue_and_inference_ms"] = (time.perf_counter() - began) * 1000
            return result
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except OverflowError as error:
            raise HTTPException(429, str(error)) from error
        except TimeoutError as error:
            raise HTTPException(503, str(error)) from error
        finally:
            admission.release()

    if features is not None:
        from .feature_routes import attach

        attach(app, features, gpu_lock, authorize, admission, preparation, read_payload)
    return app


async def read_payload(request: Request, limit: int = 2_000_000) -> bytes:
    payload = bytearray()
    try:
        with anyio.fail_after(8):
            async for chunk in request.stream():
                payload.extend(chunk)
                if len(payload) > limit:
                    raise HTTPException(413, "inference payload too large")
    except TimeoutError as error:
        raise HTTPException(408, "upload timeout") from error
    return bytes(payload)
