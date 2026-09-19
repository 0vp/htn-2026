"""Room-scoped tools; the model cannot choose a host, URL, or another room."""

import base64
import json
import re
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field

from ..robotics.actions import SkillRequest
from ..robotics.grounding import RegionRequest


class Empty(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Observe(Empty):
    sequence: int | None = Field(default=None, ge=1)


class History(Empty):
    before: int = Field(default=2**63 - 1, ge=1, le=2**63 - 1)


class Search(Empty):
    query: str = Field(min_length=1, max_length=256)


class Inspect(Empty):
    object_id: str = Field(min_length=1, max_length=120)


class Receipt(Empty):
    action_id: str = Field(pattern=r"^[a-f0-9]{32}$")


TOOLS = {
    "list_views": (
        History,
        "List sparse historical camera views retained after raw cleanup. "
        "Inspect them with observe(sequence). These are not live frames.",
    ),
    "ground_region": (
        RegionRequest,
        "Project a tight normalized bounding box from an observed "
        "upright image into measured depth. Supply that image sequence. Returns surface support "
        "and uncertainty, NOT a verified object identity, full pose or grasp.",
    ),
    "read_scene": (
        Empty,
        "Read room objects, processing state, uncertainty and robot capabilities.",
    ),
    "observe": (
        Observe,
        "Get the latest available image, or a specific observation sequence, with timing. "
        "It may be a historical retained view. Receipt time is not capture freshness.",
    ),
    "find_objects": (
        Search,
        "Search object labels and SigLIP 2 visual evidence. "
        "Results are candidates, not confirmed identities.",
    ),
    "inspect_object": (
        Inspect,
        "View historical object evidence; this is not a fresh camera observation.",
    ),
    "request_skill": (
        SkillRequest,
        "Request a bounded skill with an idempotency ID and scene revision. "
        "Inspect retrieves stored evidence; physical skills are blocked without hardware. "
        "Never equate receipt with execution.",
    ),
    "action_status": (
        Receipt,
        "Read an action receipt. Check dispatched and physical_success explicitly.",
    ),
}


def definitions():
    return [
        dict(
            type="function",
            name=name,
            description=description,
            inputSchema=model.model_json_schema(),
        )
        for name, (model, description) in TOOLS.items()
    ]


class RobotTools:
    def __init__(self, client: httpx.Client, room_id: str):
        if not re.fullmatch(r"[A-F0-9]{8}", room_id):
            raise ValueError("Invalid room code")
        self.client = client
        self.prefix = f"/v1/rooms/{room_id}"

    def get(self, suffix, **kwargs):
        response = self.client.get(self.prefix + suffix, **kwargs)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def text(value):
        return {"type": "inputText", "text": json.dumps(value, allow_nan=False)}

    def image(self, suffix):
        # Only server-derived identifiers are used, never arbitrary model-supplied URLs.
        response = self.client.get(self.prefix + suffix)
        response.raise_for_status()
        if response.headers.get("content-type", "").split(";")[0] != "image/jpeg":
            raise ValueError("Expected JPEG evidence")
        if len(response.content) > 2_000_000:
            raise ValueError("Evidence image exceeds tool limit")
        encoded = base64.b64encode(response.content).decode()
        return {"type": "inputImage", "imageUrl": f"data:image/jpeg;base64,{encoded}"}

    def call(self, name, arguments):
        try:
            if name not in TOOLS:
                raise ValueError("Unknown robot tool")
            args = TOOLS[name][0].model_validate(arguments)
            if name == "read_scene":
                content = [self.text(self.get("/scene"))]
            elif name == "find_objects":
                content = [self.text(self.get("/scene/search", params={"q": args.query}))]
            elif name == "list_views":
                content = [
                    self.text(self.get("/observations/history", params={"before": args.before}))
                ]
            elif name == "observe":
                suffix = str(args.sequence) if args.sequence is not None else "latest"
                observation = self.get(f"/observations/{suffix}")
                content = [self.text(observation)]
                if observation["rgb_available"]:
                    sequence = int(observation["sequence"])
                    content.append(self.image(f"/observations/{sequence}/image.jpg"))
            elif name == "inspect_object":
                scene = self.get("/scene")
                obj = next((o for o in scene["objects"] if o["object_id"] == args.object_id), None)
                if obj is None:
                    raise ValueError("Object not in current scene")
                content = [self.text({"revision": scene["revision"], "object": obj})]
                if obj["evidence_url"]:
                    content.append(
                        self.image(f"/objects/{quote(args.object_id, safe='')}/evidence.jpg")
                    )
            elif name == "ground_region":
                response = self.client.post(
                    self.prefix + "/observations/ground", json=args.model_dump()
                )
                response.raise_for_status()
                content = [self.text(response.json())]
            elif name == "action_status":
                content = [self.text(self.get(f"/actions/{args.action_id}"))]
            else:
                response = self.client.post(self.prefix + "/actions", json=args.model_dump())
                response.raise_for_status()
                content = [self.text(response.json())]
            return {"success": True, "contentItems": content}
        except (ValueError, httpx.HTTPError) as error:
            # Do not expose request headers, credentials or complete error response bodies.
            detail = str(error) if isinstance(error, ValueError) else type(error).__name__
            if isinstance(error, httpx.HTTPStatusError):
                detail = (
                    f"Server returned HTTP {error.response.status_code}; refresh scene or retry"
                )
            return {"success": False, "contentItems": [self.text({"error": detail})]}
