"""Fast visual check of one camera frame: "is the thing we are looking for in this picture?"

The slow planner (Codex) sets a target once; the robot's executor asks this after every new
frame while it is scanning or travelling, so a move can be cut short the moment the target
appears. The frame is already on this server, so only the question travels. A small vision
model answers in about a second; it proposes, the planner still confirms up close.
"""

import base64
import json
import os
import time

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from ..agent.remote import authorize
from ..api.models import RoomID
from .scene import Scene

MODEL = os.environ.get("HTN_WATCH_MODEL", "gpt-5.4-mini")  # ~1 s and did not hallucinate in tests
QUESTION = (
    "You watch one frame from a small robot's forward camera. Target: {target!r}. Reply ONLY "
    'JSON: {{"seen": bool, "confidence": 0-1, "x": 0-1 or null, "y": 0-1 or null, '
    '"note": "at most 12 words"}}. x, y = the target\'s centre in the image from the top-left. '
    "Say seen only if the target itself is visible, even small or far; similar objects are not it."
)


class Watch(BaseModel):
    target: str = Field(min_length=2, max_length=200)
    sequence: int | None = None


def router(state) -> APIRouter:
    routes = APIRouter(prefix="/v1/rooms", tags=["robotics"])
    observations = Scene(state).observations
    client = httpx.AsyncClient(base_url="https://api.openai.com/v1", timeout=12)

    @routes.post("/{room_id}/watch")
    async def watch(room_id: RoomID, body: Watch, authorization: str | None = Header(default=None)):
        authorize(authorization)  # Costs money per call: robot token only.
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise HTTPException(503, "Vision model is not configured")
        sequence = body.sequence or observations.latest(room_id)["sequence"]
        jpeg, _ = observations.image(room_id, sequence)
        started = time.monotonic()
        response = await client.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": MODEL,
                "reasoning_effort": "none",
                "max_completion_tokens": 120,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": QUESTION.format(target=body.target)},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "data:image/jpeg;base64,"
                                    + base64.b64encode(jpeg).decode(),
                                    "detail": "low",
                                },
                            },
                        ],
                    }
                ],
            },
        )
        if response.status_code != 200:
            raise HTTPException(502, "Vision model call failed")
        try:
            verdict = json.loads(response.json()["choices"][0]["message"]["content"])
        except (KeyError, ValueError) as error:
            raise HTTPException(502, "Vision model gave no verdict") from error
        return dict(
            sequence=sequence,
            seen=bool(verdict.get("seen")),
            confidence=float(verdict.get("confidence") or 0),
            x=verdict.get("x"),
            y=verdict.get("y"),
            note=str(verdict.get("note") or "")[:120],
            seconds=round(time.monotonic() - started, 2),
        )

    return routes
