"""Image masks require repeated measured surface support before publication."""

from dataclasses import replace

import numpy as np
from conftest import packet

from htn_backend.capture.codec import decode
from htn_backend.mapping.objects.confirmation import ObjectConfirmation
from htn_backend.mapping.projection import project


def test_repeated_identical_frame_cannot_confirm():
    frame = decode(packet(timestamp=10))
    points = project(frame, stride=1)
    confirm = ObjectConfirmation()
    detections = [{"label": "bottle", "score": 0.9, "mask": np.ones(frame.depth.shape, dtype=bool)}]
    objects = [{"object_id": "b", "label": "bottle"}]
    for _ in range(10):
        assert not confirm.update(frame, detections, objects, {"b": points})
    for stamp in [10.5, 11.1]:
        observed = replace(frame, header=frame.header.model_copy(update={"timestamp_s": stamp}))
        result = confirm.update(observed, detections, objects, {"b": points})
    assert len(result) == 1
    assert result[0]["observations"] == 3


def test_rgb_label_without_depth_support_never_confirms():
    frame = decode(packet(timestamp=10))
    points = project(frame, stride=1)
    confirm = ObjectConfirmation()
    detections = [{"label": "bottle", "score": 0.9, "mask": np.ones(frame.depth.shape, dtype=bool)}]
    for stamp in [10, 11, 12, 13]:
        observed = replace(
            frame,
            depth=np.full_like(frame.depth, 2),
            header=frame.header.model_copy(update={"timestamp_s": stamp}),
        )
        assert not confirm.update(
            observed, detections, [{"object_id": "b", "label": "bottle"}], {"b": points}
        )
