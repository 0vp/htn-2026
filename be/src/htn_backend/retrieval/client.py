"""Merge lexical and visual candidates without allowing stale evidence identities."""

import httpx


def search(scene, room_id, query):
    lexical = scene.search(room_id, query)
    try:
        with httpx.Client(timeout=5, trust_env=False) as client:
            response = client.get(
                "http://127.0.0.1:9082/search", params={"room_id": room_id, "q": query}
            )
            response.raise_for_status()
            visual = response.json()
    except (httpx.HTTPError, ValueError):
        return {**lexical, "visual_retrieval": "unavailable; lexical results only"}
    # Re-read after inference: map publications may replace an object's crop or identity.
    with scene.state.store.lock:
        current = scene.read(room_id)
        lexical = scene.search(room_id, query)
    objects = {obj["object_id"]: obj for obj in current["objects"]}
    ordered = {o["object_id"]: dict(o, retrieval=["lexical"]) for o in lexical["objects"]}
    for candidate in visual["candidates"]:
        key = candidate["object_id"]
        obj = objects.get(key)
        if obj is None or obj.get("evidence_digest") != candidate["evidence_digest"]:
            continue
        value = ordered.setdefault(key, dict(obj, retrieval=[]))
        value["retrieval"].append("visual")
        value["visual_similarity"] = candidate["cosine_similarity"]
    return dict(
        revision=current["revision"],
        search="lexical_and_siglip2",
        objects=list(ordered.values())[:50],
        visual_retrieval="available",
        model=visual["model"],
        indexed=visual["indexed"],
        score_meaning="Ranked candidates only; inspect images to confirm identity",
    )
