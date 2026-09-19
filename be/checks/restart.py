"""Verify durable upload during worker downtime and native catch-up after restart."""

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

import httpx

from htn_backend.capture.codec import decode, encode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["upload", "verify"])
    parser.add_argument("server")
    parser.add_argument("--source-room")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with httpx.Client(base_url=args.server, timeout=30) as client:
        if args.phase == "upload":
            response = client.get(f"/v1/rooms/{args.source_room}/frames?limit=1")
            response.raise_for_status()
            sequence = response.json()["frames"][0]["sequence"]
            response = client.get(f"/v1/rooms/{args.source_room}/frames/{sequence}")
            response.raise_for_status()
            frame = decode(response.content)
            response = client.post("/v1/rooms", json={"name": "Recovery validation"})
            response.raise_for_status()
            room = response.json()["room_id"]
            client.post(f"/v1/rooms/{room}/join", json={"device_id": "replay"}).raise_for_status()
            receipts, latencies = [], []
            for i, stamp in enumerate([999999, 1, 500]):
                header = frame.header.model_copy(
                    update={
                        "session_id": "recovery",
                        "epoch": 1,
                        "frame_id": i,
                        "timestamp_s": stamp,
                    }
                )
                data = encode(replace(frame, header=header))
                began = time.perf_counter()
                response = client.post(
                    f"/v1/rooms/{room}/devices/replay/frames",
                    content=data,
                    headers={"Content-Type": "application/octet-stream"},
                )
                response.raise_for_status()
                latencies.append((time.perf_counter() - began) * 1000)
                receipts.append(response.json())
                duplicate = client.post(
                    f"/v1/rooms/{room}/devices/replay/frames",
                    content=data,
                    headers={"Content-Type": "application/octet-stream"},
                )
                duplicate.raise_for_status()
                assert duplicate.json()["duplicate"]
            result = {
                "room_id": room,
                "receipts": receipts,
                "ack_ms": latencies,
                "during_downtime": client.get(f"/v1/rooms/{room}/processing").json(),
            }
            assert result["during_downtime"]["received"] == 3
            assert result["during_downtime"]["mapped"] == 0
            args.output.write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps({"room_id": room, "uploaded": 3, "duplicates_deduplicated": 3}))
        else:
            result = json.loads(args.output.read_text())
            room = result["room_id"]
            began = time.monotonic()
            while time.monotonic() - began < 180:
                try:
                    response = client.get(f"/v1/rooms/{room}/processing")
                except httpx.TransportError:
                    time.sleep(2)
                    continue
                if response.status_code in (502, 503, 504):
                    time.sleep(2)
                    continue
                response.raise_for_status()
                status = response.json()
                if status["mapped"] == 3:
                    break
                time.sleep(2)
            result["after_restart"] = status
            result["passed"] = status["mapped"] == 3 and status["pending"] == 0
            mesh = client.get(f"/v1/rooms/{room}/mesh.glb")
            mesh.raise_for_status()
            assert mesh.content[:4] == b"glTF"
            result["mesh_bytes"] = len(mesh.content)
            for receipt in result["receipts"]:
                response = client.get(f"/v1/rooms/{room}/frames/{receipt['sequence']}")
                response.raise_for_status()
                assert decode(response.content).header.session_id == "recovery"
            client.post(f"/v1/rooms/{room}/close").raise_for_status()
            args.output.write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps({"passed": result["passed"], "mapped": status["mapped"]}))
            if not result["passed"]:
                raise SystemExit(1)


if __name__ == "__main__":
    main()
