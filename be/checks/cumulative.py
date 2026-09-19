"""Native rollover and restart checks using a repeated, calibrated RGB-D capture."""

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

import httpx
import numpy as np

from htn_backend.capture.codec import decode, encode


def run(server: str, captures: Path, report: Path, phase: str):
    files = sorted(captures.glob("*.bin"))
    frames = [decode(p.read_bytes()) for p in files]
    with httpx.Client(base_url=server, timeout=30) as client:
        if phase == "upload":
            response = client.post("/v1/rooms", json={"name": "Cumulative validation"})
            response.raise_for_status()
            code = response.json()["room_id"]
            client.post(f"/v1/rooms/{code}/join", json={"device_id": "replay"}).raise_for_status()
            result = {
                "room_id": code,
                "kind": "Repeated real RGB-D captures; no accuracy ground truth",
            }
            start, count = 0, 272
        else:
            result = json.loads(report.read_text())
            code = result["room_id"]
            start, count = 272, 8
        device = "replay"
        expected = start + count
        if phase == "align":
            device = "second"
            start, count, expected = 0, len(frames), 280 + len(frames)
            client.post(f"/v1/rooms/{code}/join", json={"device_id": device}).raise_for_status()
            angle = np.deg2rad(20)
            c, s = np.cos(angle), np.sin(angle)
            transform = np.array([[c, 0, s, 1.2], [0, 1, 0, 0], [-s, 0, c, 0.8], [0, 0, 0, 1]])
        for index in range(start, start + count):
            frame = frames[index % len(frames)]
            header = frame.header.model_copy(
                update={
                    "session_id": "cumulative",
                    "epoch": 1,
                    "frame_id": index,
                    "timestamp_s": index * 0.2,
                }
            )
            if phase == "align":
                pose = np.linalg.inv(transform) @ np.array(header.camera_to_world).reshape(
                    4, 4, order="F"
                )
                header = header.model_copy(
                    update={
                        "session_id": "second",
                        "camera_to_world": tuple(pose.flatten(order="F")),
                    }
                )
            response = client.post(
                f"/v1/rooms/{code}/devices/{device}/frames",
                content=encode(replace(frame, header=header)),
                headers={"Content-Type": "application/octet-stream"},
            )
            response.raise_for_status()
        result["expected"] = expected
        report.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({"room_id": code, "uploaded": count}), flush=True)
        began = time.monotonic()
        while time.monotonic() - began < 300:
            response = client.get(f"/v1/rooms/{code}/processing")
            response.raise_for_status()
            status = response.json()
            if status["mapped"] == result["expected"] and status["pending"] == 0:
                break
            time.sleep(2)
        result[phase] = {"status": status, "drain_seconds": time.monotonic() - began}
        result["passed"] = status["mapped"] == result["expected"] and status["pending"] == 0
        if phase == "align":
            evidence = status["alignments"].get('["second","second",1]', {})
            if "room_from_local" not in evidence:
                raise AssertionError("New origin could not align after raw cleanup")
            actual = np.array(evidence["room_from_local"]).reshape(4, 4, order="F")
            delta = np.linalg.inv(transform) @ actual
            error = float(np.linalg.norm(delta[:3, 3]))
            angle = float(np.degrees(np.arccos(np.clip((np.trace(delta[:3, :3]) - 1) / 2, -1, 1))))
            result["alignment_error"] = {
                "translation_m": error,
                "rotation_deg": angle,
                "kind": "Controlled re-expression of the same RGB-D captures",
            }
            assert error < 0.08 and angle < 3
        mesh = client.get(f"/v1/rooms/{code}/mesh.glb")
        mesh.raise_for_status()
        assert mesh.content[:4] == b"glTF" and len(mesh.content) > 10000
        result[phase]["mesh_bytes"] = len(mesh.content)
        report.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({"passed": result["passed"], "mapped": status["mapped"]}), flush=True)
        if not result["passed"]:
            raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["upload", "resume", "align"])
    parser.add_argument("--server", required=True)
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    run(args.server, args.captures, args.report, args.phase)
