"""Native Hydra owner. Run with the pinned Python/ROS runtime, never shared across rooms."""

import json
import os
import struct
import sys
import time
from pathlib import Path

import numpy as np
import yaml
from scipy.spatial.transform import Rotation

from .cadence import CadencedMapper
from .config import configuration
from .export import agent_poses, object_nodes
from .packet import MAX_PACKET, pack, unpack


def read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            raise EOFError("incomplete Hydra packet")
        data.extend(chunk)
    return bytes(data)


def create(hydra, row):
    width, height, fx, fy, cx, cy = row["calibration"]
    camera = hydra.CameraConfig()
    camera.width, camera.height = int(width), int(height)
    camera.fx, camera.fy, camera.cx, camera.cy = fx, fy, cx, cy
    camera.min_range, camera.max_range = 0.15, 5.0
    camera.extrinsics = hydra.ExtrinsicsConfig()
    config = configuration(hydra, Path(os.environ["HYDRA_ROOT"]))
    # Full graph work is explicitly flushed by CadencedMapper. Capture time alone
    # must not turn accelerated replay or queued multi-phone data into graph work
    # on every input. The first native step still initializes the graph normally.
    config["active_window"]["full_update_separation_s"] = 1e9
    return CadencedMapper(
        hydra.HydraPipeline.from_config(yaml.safe_dump(config), hydra.Camera(camera, "camera"))
    )


def main():
    # Native logging must never corrupt the binary IPC channel.
    output = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    import _hydra_bindings as hydra
    import spark_dsg  # noqa: F401 -- registers native graph types with pybind

    mapper = None
    while True:
        header = sys.stdin.buffer.read(4)
        if not header:
            return
        try:
            if len(header) != 4:
                raise EOFError("incomplete Hydra packet header")
            size = struct.unpack("<I", header)[0]
            if size > MAX_PACKET:
                raise ValueError("Hydra request exceeds memory bound")
            row = unpack(read_exact(sys.stdin.buffer, size))
            started = time.perf_counter()
            loops = json.loads(str(row["loops"])) if "loops" in row else []
            for edge in loops:
                hydra.enqueue_loop_closure(
                    edge["from_timestamp_ns"], edge["to_timestamp_ns"], np.array(edge["to_T_from"])
                )
            if "flush" in row:
                if mapper is None:
                    raise ValueError("cannot flush before a capture")
                ok = mapper.flush(bool(loops))
            else:
                if mapper is None:
                    mapper = create(hydra, row)
                pose = row["pose"]
                xyzw = Rotation.from_matrix(pose[:3, :3]).as_quat()
                ok = mapper.step(
                    int(row["timestamp"]),
                    pose[:3, 3],
                    xyzw[[3, 0, 1, 2]],
                    row["depth"],
                    row["labels"],
                    row["color"],
                )
            if not ok:
                if not mapper.last_input_accepted:
                    raise RuntimeError("Hydra rejected the native input")
                output.write(
                    pack(
                        updated=np.array(False),
                        step_ms=np.array((time.perf_counter() - started) * 1000),
                    )
                )
                continue
            step_ms = (time.perf_counter() - started) * 1000
            export_started = time.perf_counter()
            graph = mapper.graph
            nodes = object_nodes(graph)
            mesh = graph.mesh
            vertices = np.asarray(mesh.get_vertices())[:3].T.astype("f4")
            faces = np.asarray(mesh.get_faces()).T.astype("i4")
            output.write(
                pack(
                    updated=np.array(True),
                    vertices=vertices,
                    triangles=faces,
                    nodes=np.array(json.dumps(nodes)),
                    step_ms=np.array(step_ms),
                    agents=agent_poses(graph),
                    submitted_loops=np.array(len(loops)),
                    export_ms=np.array((time.perf_counter() - export_started) * 1000),
                )
            )
        except Exception as error:
            output.write(pack(error=np.array(f"{type(error).__name__}: {error}"[:500])))
            return  # Never continue a potentially partially mutated map.


if __name__ == "__main__":
    main()
