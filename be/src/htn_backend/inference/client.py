"""Private batched GPU inference, with masks validated before fusion."""

import base64
import os

import httpx
import numpy as np

from ..registration.learned.remote import RemoteFeatures
from .wire import encode_image


class Detector:
    def __init__(self):
        endpoint = "http://127.0.0.1:9081"
        token = os.environ["HTN_GPU_TOKEN"]
        self.client = httpx.Client(
            base_url=endpoint, timeout=20, headers={"Authorization": f"Bearer {token}"}
        )
        self.features = RemoteFeatures(endpoint, token)

    def loop_features(self):
        return RemoteFeatures("http://127.0.0.1:9081", os.environ["HTN_GPU_TOKEN"])

    def ready(self) -> bool:
        try:
            response = self.client.get("/health", timeout=2)
            return response.status_code == 200 and response.json().get("status") == "ready"
        except (httpx.HTTPError, ValueError):
            return False

    def __call__(self, frame) -> list[dict]:
        if not frame.rgb_jpeg:
            raise ValueError("RGB is required for semantic mapping")
        response = self.client.post("/detect", content=encode_image(frame))
        response.raise_for_status()
        if len(response.content) > 2_000_000:
            raise ValueError("Detection response exceeds bound")
        data = response.json()
        if tuple(data["mask_shape"]) != frame.depth.shape or len(data["detections"]) > 128:
            raise ValueError("Invalid detection dimensions")
        rows = []
        count = frame.depth.size
        for row in data["detections"]:
            raw = base64.b64decode(row["mask"], validate=True)
            score = float(row["score"])
            if len(raw) != (count + 7) // 8 or not np.isfinite(score) or not 0 <= score <= 1:
                raise ValueError("Invalid detection mask or confidence")
            rows.append(
                {
                    "label": str(row["label"])[:80],
                    "score": score,
                    "mask": np.unpackbits(np.frombuffer(raw, dtype="u1"))[:count]
                    .reshape(frame.depth.shape)
                    .astype(bool),
                }
            )
        return rows

    def close(self) -> None:
        self.client.close()
        self.features.close()
