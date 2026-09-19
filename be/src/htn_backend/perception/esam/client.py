"""Isolated ESAM transport for calibrated room replay and pipeline validation."""

import os
import select
import struct
import subprocess
import time

import numpy as np

from ...mapping.hydra.packet import MAX_PACKET, pack, unpack
from .calibration import prepare
from .instances import InstanceCatalog


class EsamClient:
    def __init__(self, command=None):
        self.command = command or ["/opt/htn/esam-worker"]
        self.process = None
        self.failed = False
        self.catalog = InstanceCatalog()

    def transfer(self, fd, deadline, *, data=None, size=0):
        result, offset = bytearray(), 0
        target = len(data) if data is not None else size
        while offset < target:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("ESAM worker deadline exceeded; replay required")
            readable, writable, _ = select.select(
                [] if data is not None else [fd], [fd] if data is not None else [], [], remaining
            )
            if writable:
                offset += os.write(fd, data[offset : offset + 65536])
            elif readable:
                chunk = os.read(fd, min(target - offset, 65536))
                if not chunk:
                    raise RuntimeError("ESAM worker exited; replay required")
                result.extend(chunk)
                offset += len(chunk)
        return bytes(result)

    def integrate(self, frame, detections, *, reset_window=False):
        arrays = prepare(frame)
        if self.failed:
            raise RuntimeError("ESAM worker failed; replay required")
        cold = self.process is None
        try:
            if cold:
                self.process = subprocess.Popen(
                    self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0
                )
                os.set_blocking(self.process.stdin.fileno(), False)
                os.set_blocking(self.process.stdout.fileno(), False)
            deadline = time.monotonic() + (180 if cold else 30)
            arrays["reset"] = np.array(reset_window)
            self.transfer(self.process.stdin.fileno(), deadline, data=pack(**arrays))
            header = self.transfer(self.process.stdout.fileno(), deadline, size=4)
            size = struct.unpack("<I", header)[0]
            if size > MAX_PACKET:
                raise ValueError("ESAM response exceeds memory bound")
            result = unpack(self.transfer(self.process.stdout.fileno(), deadline, size=size))
            objects, surfaces = self.catalog.update(frame, detections, result)
            return (
                objects,
                surfaces,
                {
                    "esam_ms": float(result["elapsed_ms"]),
                    "window_frames": int(result["window_frames"]),
                    **{
                        key: float(result[key])
                        for key in ("preprocess_ms", "network_ms")
                        if key in result
                    },
                },
            )
        except Exception:
            self.failed = True
            self.close()
            raise

    def close(self):
        if self.process is not None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
            self.process.stdout.close()
            self.process = None
