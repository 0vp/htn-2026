"""The embodied agent's whole tool surface: six verbs, each answering with fresh senses.

Design rules borrowed from coding-agent harnesses: few orthogonal tools; every action returns
the new state so the model never acts blind; results say what actually happened (measured, and
why it stopped) so the next step can adapt; errors are instructions, not dead ends.
"""

import io
import json

import httpx
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from ..motion.link import RobotLink
from .navigator import Navigator
from .perception import Sense, Senses, data_url
from .worldmap import render


class Empty(BaseModel):
    model_config = ConfigDict(extra="forbid")


SAY = "One short sentence spoken aloud the moment this starts, while the robot moves."


class Turn(Empty):
    degrees: float = Field(ge=-180, le=180, description="+ left (counter-clockwise), - right")
    say: str | None = Field(default=None, max_length=160, description=SAY)


class Forward(Empty):
    meters: float = Field(ge=-1.0, le=3.0, description="+ ahead, - reverse (reverse is blind)")
    say: str | None = Field(default=None, max_length=160, description=SAY)


class Scan(Empty):
    views: int = Field(default=6, ge=4, le=8, description="Pictures around the full circle")
    say: str | None = Field(default=None, max_length=160, description=SAY)


class Step(Empty):
    turn: float | None = Field(default=None, ge=-180, le=180, description="Degrees, + left")
    forward: float | None = Field(default=None, ge=-1.0, le=3.0, description="Metres, + ahead")


class Path(Empty):
    steps: list[Step] = Field(min_length=1, max_length=8)
    say: str | None = Field(default=None, max_length=160, description=SAY)


class Recall(Empty):
    query: str = Field(min_length=1, max_length=120)


TOOLS = {
    "look": (
        Empty,
        "See now: camera picture, LiDAR floor map and clear distances. Free; no motion.",
    ),
    "turn": (Turn, "Rotate in place by an angle, measured by the phone. Returns the new view."),
    "forward": (
        Forward,
        "Drive straight by a distance, measured by the phone. Shortens itself before LiDAR "
        "obstacles and stops if the lane closes. Returns the new view.",
    ),
    "path": (
        Path,
        "Chain several turns and straight legs into one fluid move with no pauses to think, e.g. "
        "[{turn: 40}, {forward: 2}, {turn: -90}, {forward: 1.5}]. Use it whenever the route is "
        "clear from the last picture/map: it is several times faster than separate calls. Stops "
        "at the first leg LiDAR shortens or blocks and reports which; returns the final view.",
    ),
    "scan": (
        Scan,
        "Spin a full circle, taking a picture at each step, ending at the starting heading. "
        "Returns every picture with its turn offset and clear distance. Best first move of a "
        "search.",
    ),
    "room_map": (
        Empty,
        "Bird's-eye picture of everywhere mapped so far, from the server's accumulated LiDAR map: "
        "free floor, walls, labelled known objects with distance and the turn needed to face "
        "them, and you (yellow dot, line = facing). Use it to choose unexplored (grey) regions or "
        "to route to a remembered object. It is memory, not live: trust move results up close.",
    ),
    "recall": (
        Recall,
        "Search objects the room's cameras recorded earlier. Hints only, maybe stale.",
    ),
    "stop": (Empty, "Stop the wheels now."),
}


def definitions() -> list[dict]:
    return [
        dict(type="function", name=name, description=text, inputSchema=model.model_json_schema())
        for name, (model, text) in TOOLS.items()
    ]


def _small(jpeg: bytes, width: int) -> bytes:
    image = Image.open(io.BytesIO(jpeg)).convert("RGB")
    image.thumbnail((width, width))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=72)
    return buffer.getvalue()


class EmbodiedTools:
    def __init__(self, client: httpx.Client, room_id: str, link: RobotLink):
        self.prefix = f"/v1/rooms/{room_id}"
        self.client = client
        self.senses = Senses(client, self.prefix)
        self.navigator = Navigator(link, self.senses)
        self.moves = 0
        self.speak = None  # Set by the host: callable(text) that voices a line immediately.

    @staticmethod
    def text(value) -> dict:
        return {"type": "inputText", "text": json.dumps(value)}

    def observation(self, sense: Sense | None, extra: dict | None = None) -> list[dict]:
        if sense is None:
            note = (
                "No camera frames are arriving: the phone app is not streaming. Moves still "
                "work, timed and blind; keep them short."
            )
            return [self.text(dict(extra or {}, senses=note))]
        state = dict(extra or {}, **sense.summary(), moves_so_far=self.moves)
        if not sense.fresh:
            state["warning"] = "View is stale; the phone may have paused streaming."
        return [
            self.text(state),
            data_url(_small(sense.rgb_jpeg, 768), "jpeg"),
            data_url(sense.map_png, "png"),
        ]

    def call(self, name: str, arguments: dict) -> dict:
        try:
            args = TOOLS[name][0].model_validate(arguments or {})
            line = getattr(args, "say", None)
            if line and self.speak:
                self.speak(line)  # Talk while moving, not before or after.
            return {"success": True, "contentItems": getattr(self, f"_{name}")(args)}
        except Exception as error:  # Tell the model what to do next instead of dying.
            self.navigator.stop()
            hint = (
                f"{name} failed ({type(error).__name__}: {str(error)[:160]}). "
                "Wheels stopped. Call look and continue."
            )
            return {"success": False, "contentItems": [self.text(hint)]}

    def _look(self, _):
        return self.observation(self.senses.read())

    def _turn(self, args):
        before = self.senses.read(render=False)
        result = self.navigator.turn(args.degrees)
        self.moves += 1
        return self.observation(self.navigator.settle_and_sense(before), dict(turn=result))

    def _forward(self, args):
        before = self.senses.read(render=False)
        result = self.navigator.forward(args.meters, before)
        self.moves += 1
        return self.observation(self.navigator.settle_and_sense(before), dict(forward=result))

    def _path(self, args):
        before = self.senses.read(render=False)
        done, halted = [], None
        for index, step in enumerate(args.steps):
            if step.turn:
                result = self.navigator.turn(step.turn)
            elif step.forward:
                result = self.navigator.forward(step.forward, self.senses.read(render=False))
            else:
                continue
            self.moves += 1
            done.append(dict(step=index, **result))
            if (
                not result.get("moved")
                or result.get("stopped_by")
                or result.get("shortened_because")
            ):
                halted = f"stopped at step {index}; remaining steps were not run. Look and re-plan."
                break
        return self.observation(
            self.navigator.settle_and_sense(before), dict(path=done, halted=halted)
        )

    def _scan(self, args):
        step, items, views = 360.0 / args.views, [], []
        for index in range(args.views):
            sense = self.senses.read(render=False)
            if sense:
                views.append(
                    dict(
                        view=index,
                        turned_left_deg=round(index * step),
                        clear_ahead_m=sense.summary()["clear_ahead_m"],
                    )
                )
                items.append(data_url(_small(sense.rgb_jpeg, 512), "jpeg"))
            result = self.navigator.turn(step)
            if not result["moved"]:
                views.append(dict(aborted=result["stopped_by"]))
                break
            self.navigator.settle_and_sense(sense)
        self.moves += 1
        note = "Pictures follow in order. To face view k, turn(k * step_deg) left from here."
        return [
            self.text(dict(scan=views, step_deg=round(step), note=note, moves_so_far=self.moves)),
            *items,
        ]

    def _room_map(self, _):
        sense = self.senses.read(render=False)
        if sense is None:
            return [self.text("No phone pose yet, so the robot cannot be placed on the map.")]
        drawn = render(self.client, self.prefix, sense.position, sense.heading_deg)
        if drawn is None:
            return [self.text("The server has not built a map yet. Explore with scan and forward.")]
        return [self.text(drawn[1]), data_url(drawn[0], "png")]

    def _recall(self, args):
        response = self.client.get(self.prefix + "/scene/search", params={"q": args.query})
        response.raise_for_status()
        return [self.text(response.json())]

    def _stop(self, _):
        self.navigator.stop()
        return self.observation(self.senses.read(), dict(stopped=True))
