"""Where the robot is in the wider world: nearby buildings and entrances from OpenStreetMap.

The phone reports GPS and a true-north compass reading tied to its tracking pose. Combined with
the current pose, that gives the compass direction the robot faces now, so named buildings
("E6", 82 m east-south-east) become a turn and a distance. Indoors GPS is off by 10-30 m and the
compass by ~10 degrees: this is for choosing a direction and an exit, not for driving blind.
"""

import json
import math
from pathlib import Path

import httpx
import numpy as np
from PIL import Image, ImageDraw

OVERPASS = "https://overpass-api.de/api/interpreter"
RADIUS_M = 400
CACHE = Path(__file__).resolve().parents[6] / "robot/scripts/.places_cache.json"
CARDINALS = (
    "north",
    "north-east",
    "east",
    "south-east",
    "south",
    "south-west",
    "west",
    "north-west",
)


def wrap(degrees: float) -> float:
    return (degrees + 180.0) % 360.0 - 180.0


def arkit_heading(camera_to_world) -> float:
    pose = np.array(camera_to_world, dtype=np.float64).reshape(4, 4).T
    forward = pose[:3, :3] @ np.array([0.0, 0.0, -1.0])
    return math.degrees(math.atan2(-forward[0], -forward[2]))


def fetch(lat: float, lon: float) -> list[dict]:
    key = f"{lat:.3f},{lon:.3f}"
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    if key not in cache:
        around = f"(around:{RADIUS_M},{lat},{lon})"
        query = (
            f'[out:json][timeout:25];(way{around}["building"]["name"];'
            f'relation{around}["building"]["name"];node{around}["entrance"];);out center tags 300;'
        )
        response = httpx.post(
            OVERPASS, data={"data": query}, timeout=40, headers={"User-Agent": "htn-robot/1.0"}
        )
        response.raise_for_status()
        cache[key] = response.json()["elements"]
        CACHE.write_text(json.dumps(cache))
    return cache[key]


def offset_m(lat0, lon0, lat, lon) -> tuple[float, float]:
    north = (lat - lat0) * 111_320
    east = (lon - lon0) * 111_320 * math.cos(math.radians(lat0))
    return east, north


def survey(client: httpx.Client, prefix: str, sense, query: str | None):
    """(summary dict, PNG bytes) of named buildings around the robot, or (reason, None)."""
    anchors = client.get(prefix + "/geography", timeout=6).json().get("anchors") or []
    if not anchors:
        return "The phone has not reported a GPS position yet (needs location permission).", None
    entry = anchors[-1]
    anchor = entry.get("anchor", entry)
    lat, lon = anchor["latitude"], anchor["longitude"]
    facing = None
    compass = anchor.get("heading") or {}
    same_session = sense is not None and entry.get("session_id") == sense.header.session_id
    if compass.get("degrees") is not None and same_session:
        then = arkit_heading(compass["camera_to_world"])
        # Turning left raises the tracking heading and lowers the compass bearing.
        facing = (compass["degrees"] - (sense.heading_deg - then)) % 360
    places, doors = [], []
    for element in fetch(lat, lon):
        centre = element.get("center", element)
        east, north = offset_m(lat, lon, centre["lat"], centre["lon"])
        tags = element.get("tags", {})
        item = dict(
            east=east,
            north=north,
            distance_m=round(math.hypot(east, north)),
            bearing=round(math.degrees(math.atan2(east, north)) % 360),
        )
        if element["type"] == "node":
            doors.append(dict(item, kind=tags.get("entrance")))
        else:
            places.append(
                dict(item, name=tags.get("name"), ref=tags.get("ref") or tags.get("short_name"))
            )

    def describe(item):
        out = dict(
            distance_m=item["distance_m"],
            compass_deg=item["bearing"],
            direction=CARDINALS[round(item["bearing"] / 45) % 8],
        )
        if facing is not None:
            out["turn_left_deg"] = round(wrap(facing - item["bearing"]))
        return out

    places.sort(key=lambda p: p["distance_m"])
    wanted = (query or "").lower().split()
    matches = [
        p for p in places if wanted and all(w in f"{p['name']} {p['ref']}".lower() for w in wanted)
    ]
    listed = []
    for place in (matches or places)[:8]:
        near = sorted(
            doors, key=lambda d: math.hypot(d["east"] - place["east"], d["north"] - place["north"])
        )[:2]
        listed.append(
            dict(
                name=place["name"],
                ref=place["ref"],
                **describe(place),
                entrances=[dict(kind=d["kind"], **describe(d)) for d in near],
            )
        )
    summary = dict(
        you=dict(
            latitude=round(lat, 5),
            longitude=round(lon, 5),
            gps_accuracy_m=round(anchor.get("horizontal_accuracy_m") or 0),
            facing_compass_deg=None if facing is None else round(facing),
        ),
        buildings=listed,
        note="GPS and compass are rough indoors. Use this to pick a direction and an exit door, "
        "then navigate by what you see. You are probably inside the nearest building.",
    )
    return summary, _draw(places, doors, facing)


def _draw(places, doors, facing) -> bytes:
    size, scale = 560, 560 / (2 * RADIUS_M)
    image = Image.new("RGB", (size, size), (28, 30, 36))
    draw = ImageDraw.Draw(image)
    middle = size // 2

    def pixel(item):
        return middle + item["east"] * scale, middle - item["north"] * scale

    for metres in (100, 200, 300):
        r = metres * scale
        draw.ellipse([middle - r, middle - r, middle + r, middle + r], outline=(60, 66, 80))
        draw.text((middle + 3, middle - r - 12), f"{metres} m", fill=(110, 120, 140))
    for door in doors:
        x, y = pixel(door)
        draw.rectangle([x - 1, y - 1, x + 1, y + 1], fill=(240, 170, 40))
    for place in places:
        x, y = pixel(place)
        draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(90, 150, 255))
        draw.text((x + 6, y - 6), place["ref"] or (place["name"] or "")[:18], fill=(200, 215, 255))
    draw.text((middle - 4, 4), "N", fill=(255, 255, 255))
    draw.ellipse([middle - 6, middle - 6, middle + 6, middle + 6], fill=(255, 210, 0))
    if facing is not None:
        theta = math.radians(facing)
        tip = (middle + math.sin(theta) * 34, middle - math.cos(theta) * 34)
        draw.line([middle, middle, *tip], fill=(255, 210, 0), width=4)
        draw.text((tip[0] + 4, tip[1] - 6), "you face", fill=(255, 210, 0))
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
