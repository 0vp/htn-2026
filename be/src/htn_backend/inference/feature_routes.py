"""Private bounded keyframe extraction and correspondence RPC routes."""

import json

import anyio
from fastapi import Header, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from .batching import MicroBatcher
from .wire import decode_image


def attach(app, features, lock, authorize, admission, preparation, read_payload):
    def extract_batch(values):
        with lock:
            return features.batch(values)

    def match_batch(values):
        output = []
        with lock:
            for pairs in values:
                try:
                    output.append(features.match(pairs))
                except KeyError:
                    output.append(None)
        return output

    extracts = MicroBatcher(extract_batch, size=8)
    matches = MicroBatcher(match_batch, size=4, delay_s=0)
    app.state.workers.extend([extracts, matches])
    app.state.features = features

    async def respond(value):
        # These model outputs are already plain lists/dicts/scalars. Avoid FastAPI's
        # recursive object conversion over thousands of known numeric coordinates.
        async with preparation:
            return await run_in_threadpool(
                lambda: Response(
                    json.dumps(value, allow_nan=False, separators=(",", ":")),
                    media_type="application/json",
                )
            )

    async def enter():
        try:
            admission.acquire_nowait()
        except anyio.WouldBlock as error:
            raise HTTPException(429, "inference queue full") from error

    @app.post("/features")
    async def extract(request: Request, authorization: str = Header(default="")):
        authorize(authorization)
        await enter()
        try:
            payload = await read_payload(request)
            async with preparation:
                prepared = await run_in_threadpool(
                    lambda: features.prepare(decode_image(payload), payload)
                )
            return await respond(await extracts.submit(prepared))
        except (ValueError, KeyError) as error:
            raise HTTPException(400, str(error)) from error
        except OverflowError as error:
            raise HTTPException(429, str(error)) from error
        except TimeoutError as error:
            raise HTTPException(503, str(error)) from error
        finally:
            admission.release()

    @app.post("/match")
    async def match(request: Request, authorization: str = Header(default="")):
        authorize(authorization)
        await enter()
        try:
            data = json.loads(await read_payload(request, 16_384))
            pairs = data.get("pairs") if isinstance(data, dict) else None
            if not isinstance(pairs, list) or not 1 <= len(pairs) <= 32:
                raise ValueError("match request must contain 1 to 32 pairs")
            for pair in pairs:
                if not isinstance(pair, list) or len(pair) != 2:
                    raise ValueError("invalid feature pair")
                if any(
                    not isinstance(key, str)
                    or len(key) != 64
                    or any(c not in "0123456789abcdef" for c in key)
                    for key in pair
                ):
                    raise ValueError("invalid feature ID")
            result = await matches.submit(pairs)
            if result is None:
                raise HTTPException(409, "feature cache expired; resend keyframes")
            return await respond(result)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except OverflowError as error:
            raise HTTPException(429, str(error)) from error
        except TimeoutError as error:
            raise HTTPException(503, str(error)) from error
        finally:
            admission.release()
