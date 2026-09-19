"""Exercise a deployed capture service with two concurrent synthetic RGB-D senders."""

import argparse
import asyncio
import hashlib
import io
import json
import statistics
import struct
import time
import zlib
from pathlib import Path

import httpx
import numpy as np
from PIL import Image
from websockets.asyncio.client import connect

from htn_backend.capture.codec import encode
from htn_backend.capture.frame import Frame, FrameHeader


def payload(index: int, device: str) -> bytes:
    rng = np.random.default_rng(7)
    image = io.BytesIO()
    Image.fromarray(rng.integers(0, 256, (720, 960, 3), dtype="u1")).save(
        image, format="JPEG", quality=75
    )
    header = FrameHeader(
        session_id=device,
        epoch=index // 25,
        frame_id=index % 25,
        timestamp_s=float(50 - index),
        tracking="normal",
        camera_convention="arkit",
        depth_width=256,
        depth_height=192,
        rgb_width=960,
        rgb_height=720,
        rgb_bytes=len(image.getvalue()),
        fx=200,
        fy=200,
        cx=128,
        cy=96,
        camera_to_world=tuple(np.eye(4).flatten(order="F")),
    )
    return encode(
        Frame(
            header,
            rng.uniform(0.3, 4, (192, 256)).astype("f4"),
            np.full((192, 256), 2, dtype="u1"),
            image.getvalue(),
        )
    )


async def run(base: str, output: Path) -> None:
    base = base.rstrip("/")
    async with httpx.AsyncClient(base_url=base, timeout=30) as client:
        health = (await client.get("/health")).json()
        assert health["storage"] == "durable"
        response = await client.post("/v1/rooms", json={"name": "Upload check"})
        response.raise_for_status()
        room = response.json()["room_id"]
        for device in ("phone-a", "phone-b"):
            (
                await client.post(f"/v1/rooms/{room}/join", json={"device_id": device})
            ).raise_for_status()

        async def sender(device: str) -> list[dict]:
            url = base.replace("https://", "wss://").replace("http://", "ws://")
            path = f"/v1/rooms/{room}/devices/{device}"
            receipts = []
            for start in (0, 25):
                async with connect(url + path + "/stream", compression=None, open_timeout=20) as ws:
                    for index in range(start, start + 25):
                        data = payload(index, device)
                        began = time.perf_counter()
                        await ws.send(data)
                        result = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                        elapsed = (time.perf_counter() - began) * 1000
                        assert result.get("stored") and not result["duplicate"], result
                        assert result["sha256"] == hashlib.sha256(data).hexdigest()
                        receipts.append({**result, "ack_ms": elapsed})
            # Reconnect and retry through a different transport and compression envelope.
            data = payload(0, device)
            compressor = zlib.compressobj(wbits=-15)
            compressed = (
                b"R3Z1"
                + struct.pack("<I", len(data))
                + compressor.compress(data)
                + compressor.flush()
            )
            duplicate = await client.post(
                path + "/frames",
                content=compressed,
                headers={"Content-Type": "application/octet-stream"},
            )
            duplicate.raise_for_status()
            assert duplicate.json()["duplicate"]
            assert duplicate.json()["sequence"] == receipts[0]["sequence"]
            for receipt in (receipts[0], receipts[-1]):
                stored = await client.get(f"/v1/rooms/{room}/frames/{receipt['sequence']}")
                stored.raise_for_status()
                assert hashlib.sha256(stored.content).hexdigest() == receipt["sha256"]
            return receipts

        began = time.perf_counter()
        groups = await asyncio.gather(sender("phone-a"), sender("phone-b"))
        elapsed = time.perf_counter() - began
        rows = [r for group in groups for r in group]
        state = (await client.get(f"/v1/rooms/{room}")).json()
        assert state["frames_stored"] == 100
        assert state["bytes_stored"] == sum(r["bytes"] for r in rows)
        other = (await client.post("/v1/rooms", json={"name": "Isolation check"})).json()["room_id"]
        assert (
            await client.get(f"/v1/rooms/{other}/frames/{rows[0]['sequence']}")
        ).status_code == 404
        report = dict(
            room_id=room,
            isolation_room_id=other,
            frames_stored=100,
            bytes_stored=state["bytes_stored"],
            senders=2,
            ack_median_ms=statistics.median(r["ack_ms"] for r in rows),
            ack_p95_ms=float(np.percentile([r["ack_ms"] for r in rows], 95)),
            elapsed_s=elapsed,
            duplicates_deduplicated=True,
            raw_bytes_verified=True,
            room_isolation=True,
            samples=[rows[0], rows[-1]],
            scope="Synthetic RGB-D transport; acknowledgement includes network and commit. "
            "No mapping, inference, alignment or physical phone validation.",
        )
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    asyncio.run(run(args.base, args.output))
