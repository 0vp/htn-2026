"""Upload through room publication and checkpointing with four independent instances."""

from dataclasses import replace

from conftest import room, upload
from test_mapping import Detector as EmptyDetector
from test_mapping import Native

from htn_backend.capture.codec import encode
from htn_backend.perception.esam.fusion import HydraEsam
from htn_backend.perception.esam.instances import InstanceCatalog
from htn_backend.processing.room import RoomProcessor
from htn_backend.processing.state import ProcessingState

from .test_instances import scene


class Geometry(Native):
    def integrate(self, frame, detections, loops=()):
        return super().integrate(frame, detections)

    def flush(self, loops=()):
        return super().flush()


class Detector(EmptyDetector):
    def __call__(self, frame):
        return scene()[1]


class MeasuredInstances:
    def __init__(self):
        self.catalog = InstanceCatalog()

    def integrate(self, frame, detections, reset_window=False):
        objects, surfaces = self.catalog.update(frame, detections, scene()[2])
        return objects, surfaces, {"esam_ms": 1, "window_frames": 1}

    def close(self):
        pass


def test_distinct_instances_survive_publication_search_and_checkpoint(client):
    code = room(client)
    frame, _, _ = scene()
    for index in range(12):
        capture = replace(
            frame,
            header=frame.header.model_copy(
                update={
                    "frame_id": index,
                    "timestamp_s": index * 0.2 + 1,
                }
            ),
        )
        assert upload(client, code, encode(capture)).status_code == 200
    state = ProcessingState(client.app.state.store)
    processor = RoomProcessor(
        state, code, Detector(), mapper_factory=lambda: HydraEsam(Geometry, MeasuredInstances)
    )
    try:
        while processor.step():
            pass
        assert state.status(code)["mapped"] == 12
        assert state.snapshot(code)["metadata"]["instance_backend"] == "esam-e"
        objects = client.get(f"/v1/rooms/{code}/objects", params={"q": "table"}).json()["objects"]
        assert len(objects) == 4
        identifiers = {obj["object_id"] for obj in objects}
        assert len(identifiers) == 4
        assert all(obj["identity_status"] == "esam_instance" for obj in objects)
        for identifier in identifiers:
            assert (
                client.get(f"/v1/rooms/{code}/objects/{identifier}/evidence.jpg").status_code == 200
            )
        processor.seal()
        assert len(processor.atlas.objects) == 4
        assert {obj["object_id"] for obj in processor.atlas.objects} == identifiers
    finally:
        processor.close()
