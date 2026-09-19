"""Controlled two-origin replay with known metric transform; not independent phone accuracy."""

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

import httpx
import numpy as np

from htn_backend.capture.codec import decode, encode


def run(server: str, source_room: str) -> dict:
    with httpx.Client(base_url=server, timeout=30) as client:
        manifest = client.get(f"/v1/rooms/{source_room}/frames?limit=200")
        manifest.raise_for_status()
        rows = manifest.json()["frames"]
        chosen = [rows[i] for i in np.linspace(0, len(rows) - 1, min(16, len(rows)), dtype=int)]
        frames = []
        for row in chosen:
            response = client.get(f"/v1/rooms/{source_room}/frames/{row['sequence']}")
            response.raise_for_status()
            frames.append(decode(response.content))
        response = client.post("/v1/rooms", json={"name": "Alignment validation"})
        response.raise_for_status()
        room = response.json()["room_id"]
        angle = np.deg2rad(20)
        c, s = np.cos(angle), np.sin(angle)
        expected = np.array([[c, 0, s, 1.2], [0, 1, 0, 0], [-s, 0, c, 0.8], [0, 0, 0, 1]])
        for device, transform in [("reference", np.eye(4)), ("second", expected)]:
            response = client.post(f"/v1/rooms/{room}/join", json={"device_id": device})
            response.raise_for_status()
            for index, frame in enumerate(frames):
                pose = np.linalg.inv(transform) @ np.array(frame.header.camera_to_world).reshape(
                    4, 4, order="F"
                )
                header = frame.header.model_copy(
                    update={
                        "session_id": device,
                        "epoch": 1,
                        "frame_id": index,
                        "camera_to_world": tuple(pose.flatten(order="F")),
                        "timestamp_s": frame.header.timestamp_s
                        + (10000 if device == "second" else 0),
                    }
                )
                response = client.post(
                    f"/v1/rooms/{room}/devices/{device}/frames",
                    content=encode(replace(frame, header=header)),
                    headers={"Content-Type": "application/octet-stream"},
                )
                response.raise_for_status()
        began = time.monotonic()
        while time.monotonic() - began < 240:
            response = client.get(f"/v1/rooms/{room}/processing")
            response.raise_for_status()
            status = response.json()
            if status["mapped"] == 2 * len(frames):
                break
            time.sleep(2)
        evidence = status["alignments"].get('["second","second",1]', {})
        actual = evidence.get("room_from_local")
        error = None
        if actual is not None:
            actual = np.array(actual).reshape(4, 4, order="F")
            delta = np.linalg.inv(expected) @ actual
            error = {
                "translation_m": float(np.linalg.norm(delta[:3, 3])),
                "rotation_deg": float(
                    np.degrees(np.arccos(np.clip((np.trace(delta[:3, :3]) - 1) / 2, -1, 1)))
                ),
            }
        result = {
            "test": "controlled_two_origin_replay",
            "room_id": room,
            "frames": 2 * len(frames),
            "status": status,
            "transform_error": error,
            "limitations": "Same measured images re-expressed in two origins; not a real "
            "independent multi-phone accuracy benchmark.",
        }
        result["passed"] = bool(
            error
            and error["translation_m"] < 0.08
            and error["rotation_deg"] < 3
            and status["mapped"] == 2 * len(frames)
        )
        client.post(f"/v1/rooms/{room}/close").raise_for_status()
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("server")
    parser.add_argument("source_room")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.server, args.source_room)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "room_id": report["room_id"],
                "transform_error": report["transform_error"],
            }
        )
    )
    raise SystemExit(0 if report["passed"] else 1)
