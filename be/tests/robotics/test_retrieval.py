"""Visual retrieval caching and ranking are tested independently from model accuracy."""

import io

import numpy as np
from conftest import room
from PIL import Image

from htn_backend.processing.state import ProcessingState
from htn_backend.retrieval.index import EvidenceIndex


def jpeg(color):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, format="JPEG")
    return buffer.getvalue()


class Encoder:
    def __init__(self):
        self.image_calls = 0
        self.text_calls = 0

    def encode(self, *, images=None, text=None):
        if images is not None:
            self.image_calls += 1
            return np.array(
                [[1, 0] if i.getpixel((0, 0))[0] > 100 else [0, 1] for i in images],
                dtype=np.float32,
            )
        self.text_calls += 1
        return np.array([[1, 0]], dtype=np.float32)


def test_visual_index_caches_and_prunes_evidence(client):
    code = room(client)
    state = ProcessingState(client.app.state.store)
    objects = [{"object_id": "a", "label": "bottle"}, {"object_id": "b", "label": "chair"}]
    evidence = {
        "a": {"digest": "red", "jpeg": jpeg("red")},
        "b": {"digest": "blue", "jpeg": jpeg("blue")},
    }
    state.publish(code, b"mesh", objects, {}, [], evidence)
    encoder = Encoder()
    index = EvidenceIndex(state.store, encoder)
    found = index.search(code, "red thing")
    assert found["candidates"][0]["object_id"] == "a"
    assert found["indexed"] == 2
    index.search(code, "red thing")
    assert encoder.image_calls == 1 and encoder.text_calls == 1
    # Reopening the index uses durable image vectors, not a Python-only cache.
    EvidenceIndex(state.store, encoder).search(code, "red thing")
    assert encoder.image_calls == 1
    state.publish(code, b"mesh", objects[:1], {}, [], {"a": evidence["a"]})
    assert len(index.search(code, "red thing")["candidates"]) == 1
    assert state.store.db.execute("SELECT COUNT(*) FROM visual_embeddings").fetchone()[0] == 1
    other = room(client)
    assert index.search(other, "red thing")["candidates"] == []


def test_search_rejects_embedding_from_superseded_crop(client, monkeypatch):
    import htn_backend.retrieval.client as retrieval
    from htn_backend.robotics.scene import Scene

    code = room(client)
    state = ProcessingState(client.app.state.store)
    state.publish(
        code, b"mesh", [{"object_id": "a", "label": "chair", "evidence_digest": "new"}], {}, []
    )

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "candidates": [
                    {"object_id": "a", "evidence_digest": "old", "cosine_similarity": 1}
                ],
                "model": "test",
                "indexed": 1,
            }

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(retrieval.httpx, "Client", Client)
    assert retrieval.search(Scene(state), code, "bottle")["objects"] == []
