"""One isolated native process per room; failures require explicit journal replay."""

import json
import os
import select
import struct
import subprocess
import time

import numpy as np

from ..loops.packet import encode_edges
from .packet import MAX_PACKET, pack, prepare, unpack


class HydraClient:
    def __init__(self, command=None):
        self.command = command or [os.environ.get("HTN_HYDRA_WORKER", "/opt/htn/hydra-worker")]
        self.process = None
        self.calibration = None
        self.failed = False
        self.frames = 0

    def _transfer(self, fd, data=None, size=None, deadline=None):
        chunks = bytearray()
        offset = 0
        while offset < (len(data) if data is not None else size):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Hydra worker deadline exceeded; room replay required")
            readable, writable, _ = select.select(
                [fd] if data is None else [], [fd] if data is not None else [], [], remaining
            )
            if not readable and not writable:
                continue
            if data is not None:
                offset += os.write(fd, data[offset : offset + 65536])
            else:
                chunk = os.read(fd, min(size - offset, 65536))
                if not chunk:
                    raise RuntimeError("Hydra worker exited; room replay required")
                chunks.extend(chunk)
                offset += len(chunk)
        return bytes(chunks)

    def integrate(self, frame, detections, loops=()):
        if self.failed:
            raise RuntimeError("Hydra worker failed; room replay required")
        arrays, calibration = prepare(frame, detections, self.calibration)
        if loops:
            arrays["loops"] = np.array(json.dumps(encode_edges(loops)))
        result = self._request(arrays)
        self.calibration = calibration
        self.frames += 1
        return result

    def flush(self, loops=()):
        if self.process is None:
            return None
        arrays = dict(flush=np.array(True))
        if loops:
            arrays["loops"] = np.array(json.dumps(encode_edges(loops)))
        return self._request(arrays)

    def _request(self, arrays):
        if self.failed:
            raise RuntimeError("Hydra worker failed; room replay required")
        try:
            if self.process is None:
                self.process = subprocess.Popen(
                    self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0
                )
                os.set_blocking(self.process.stdin.fileno(), False)
                os.set_blocking(self.process.stdout.fileno(), False)
            deadline = time.monotonic() + 12
            self._transfer(self.process.stdin.fileno(), data=pack(**arrays), deadline=deadline)
            header = self._transfer(self.process.stdout.fileno(), size=4, deadline=deadline)
            size = struct.unpack("<I", header)[0]
            if size > MAX_PACKET:
                raise ValueError("Hydra response exceeds bound")
            result = unpack(
                self._transfer(self.process.stdout.fileno(), size=size, deadline=deadline)
            )
            if "error" in result:
                raise RuntimeError(str(result["error"]))
            return result
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
