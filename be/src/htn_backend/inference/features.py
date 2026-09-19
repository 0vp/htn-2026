"""Pinned XFeat GPU extraction, content-addressed descriptors and mutual matching."""

import hashlib
from collections import OrderedDict
from io import BytesIO

import cv2
import numpy as np
import torch
from PIL import Image

from ..perception.orientation import upright_quarter_turns


class Features:
    def __init__(self):
        from modules.xfeat import XFeat

        self.model = XFeat(top_k=1600)
        self.cache = OrderedDict()

    def prepare(self, frame, payload):
        with Image.open(BytesIO(frame.rgb_jpeg)) as image:
            if image.size != (frame.header.rgb_width, frame.header.rgb_height):
                raise ValueError("feature RGB dimensions disagree with metadata")
            raw = np.asarray(image.convert("RGB"))
        turns = upright_quarter_turns(frame.header)
        upright = np.rot90(raw, turns)
        height, width = upright.shape[:2]
        scale = 640 / max(height, width)
        resized = cv2.resize(upright, (round(width * scale), round(height * scale)))
        return hashlib.sha256(payload).hexdigest(), frame.header, turns, (width, height), resized

    def batch(self, prepared):
        output = [None] * len(prepared)
        groups = {}
        for index, item in enumerate(prepared):
            key = item[0]
            if key in self.cache:
                self.cache.move_to_end(key)
                output[index] = self.cache[key][1]
            else:
                groups.setdefault(item[-1].shape, []).append(index)
        with torch.inference_mode():
            for indices in groups.values():
                tensors = (
                    torch.stack(
                        [torch.from_numpy(prepared[i][-1].copy()).permute(2, 0, 1) for i in indices]
                    )
                    .cuda()
                    .float()
                    / 255
                )
                values = self.model.detectAndCompute(tensors)
                for index, features in zip(indices, values, strict=True):
                    key, h, turns, size, resized = prepared[index]
                    xy = features["keypoints"].cpu().numpy()
                    xy = (xy + 0.5) * np.array(size) / [resized.shape[1], resized.shape[0]] - 0.5
                    u, v = xy.T
                    if turns == 1:
                        u, v = h.rgb_width - 1 - v, u
                    elif turns == 2:
                        u, v = h.rgb_width - 1 - u, h.rgb_height - 1 - v
                    elif turns == 3:
                        u, v = v, h.rgb_height - 1 - u
                    normalized = (np.column_stack([u, v]) + 0.5) / [h.rgb_width, h.rgb_height]
                    result = dict(id=key, keypoints=normalized.tolist(), model="xfeat-1600")
                    self.cache[key] = (features["descriptors"], result)
                    self.cache.move_to_end(key)
                    output[index] = result
        while len(self.cache) > 512:
            self.cache.popitem(last=False)
        return output

    def match(self, pairs):
        missing = [key for pair in pairs for key in pair if key not in self.cache]
        if missing:
            raise KeyError("feature cache expired")
        results = []
        with torch.inference_mode():
            for left, right in pairs:
                a, b = self.cache[left][0], self.cache[right][0]
                self.cache.move_to_end(left)
                self.cache.move_to_end(right)
                if not len(a) or not len(b):
                    results.append(dict(keypoints0=[], keypoints1=[], scores=[]))
                    continue
                similarity = a @ b.T
                scores, forward = similarity.max(dim=1)
                backward = similarity.argmax(dim=0)
                indices = torch.arange(len(a), device=a.device)
                good = (backward[forward] == indices) & (scores > 0.82)
                index_a = indices[good].cpu().numpy()
                index_b = forward[good].cpu().numpy()
                xy_a = np.asarray(self.cache[left][1]["keypoints"])[index_a]
                xy_b = np.asarray(self.cache[right][1]["keypoints"])[index_b]
                results.append(
                    dict(
                        keypoints0=xy_a.tolist(),
                        keypoints1=xy_b.tolist(),
                        scores=scores[good].cpu().tolist(),
                    )
                )
        return results
