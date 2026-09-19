"""Verify a completed upload check after restarting the service."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

import httpx


async def run(base: str, report_path: Path) -> None:
    report = json.loads(report_path.read_text())
    retries = 0
    async with httpx.AsyncClient(base_url=base, timeout=10) as client:

        async def get(path: str) -> httpx.Response:
            nonlocal retries
            for attempt in range(3):
                try:
                    response = await client.get(path)
                    response.raise_for_status()
                    return response
                except httpx.TransportError:
                    if attempt == 2:
                        raise
                    retries += 1
                    await asyncio.sleep(0.5)
            raise AssertionError("unreachable")

        room = report["room_id"]
        state = (await get(f"/v1/rooms/{room}")).json()
        assert state["frames_stored"] == report["frames_stored"]
        rows = (await get(f"/v1/rooms/{room}/frames?limit=200")).json()["frames"]
        assert len(rows) == report["frames_stored"]
        for index, row in enumerate(rows):
            response = await get(f"/v1/rooms/{room}/frames/{row['sequence']}")
            assert hashlib.sha256(response.content).hexdigest() == row["sha256"]
            if index % 25 == 24:
                print(f"Verified {index + 1}/{len(rows)} frame hashes", flush=True)
        row = rows[0]
        raw = (await get(f"/v1/rooms/{room}/frames/{row['sequence']}")).content
        response = await client.post(
            f"/v1/rooms/{room}/devices/{row['device_id']}/frames",
            content=raw,
            headers={"Content-Type": "application/octet-stream"},
        )
        response.raise_for_status()
        assert response.json()["duplicate"]
        report.update(
            restart_survived=True,
            verified_frame_hashes_after_restart=len(rows),
            retry_after_restart_deduplicated=True,
            verification_transport_retries=retries,
        )
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print("Restart verification passed", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base")
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    asyncio.run(asyncio.wait_for(run(args.base, args.report), timeout=240))
