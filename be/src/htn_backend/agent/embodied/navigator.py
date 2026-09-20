"""Smooth, measured moves: one continuous command per move, checked by the phone's pose.

The phone's ARKit pose fuses its gyroscope, accelerometer and camera, but reaches the laptop
~0.5-1 s late: too late to stop on (a 60 degree turn overshot to 153). So a move is timed from a
learned rate (deg/s, m/s), streamed as one steady command the firmware ramps, then measured
from the pose. Each measurement refines the rate, and a turn that lands off gets one
corrective turn. Forward moves still poll LiDAR and stop if the lane closes.
"""

import json
import math
import time
from pathlib import Path

from ..motion.link import RobotLink
from ..motion.skills import Motion
from . import planner
from .perception import Sense, Senses, wait_fresh

TURN_LEVEL, DRIVE_LEVEL = 0.3, 0.3
# Starting rates at these levels; every measured move refines them (robot/scripts/rates.json).
DEFAULT_RATES = {"turn": 48.0, "forward": 0.35}  # deg/s, m/s
RATE_LIMITS = {"turn": (15.0, 150.0), "forward": (0.08, 1.2)}
RATES_FILE = Path(__file__).resolve().parents[5] / "robot/scripts/rates.json"
DEAD_TIME_S = 0.25  # Ramp-up before the base is really moving.
STOP_MARGIN_M = 0.65  # From the phone at the centre: leaves ~0.25 m between hull and obstacle.
LEG_M = 2.0  # Re-sense and re-plan at least this often while following a route.
ARRIVE_M = 0.35
POLL_S = 0.3
MAX_TURN_DEG, MAX_FORWARD_M = 180.0, 3.0


def wrap(degrees: float) -> float:
    return (degrees + 180.0) % 360.0 - 180.0


class Navigator:
    def __init__(self, link: RobotLink, senses: Senses):
        self.link, self.senses, self.motion = link, senses, Motion(link)
        self.grid: planner.Grid | None = None
        self.last_position = None
        self.rates = dict(DEFAULT_RATES)
        if RATES_FILE.exists():
            self.rates.update(json.loads(RATES_FILE.read_text()))

    def blockers(self) -> list[str]:
        telemetry, age = self.link.telemetry()
        return self.motion._blockers(telemetry, age)

    def stop(self) -> None:
        self.link.release()

    def turn(self, degrees: float) -> dict:
        degrees = max(-MAX_TURN_DEG, min(MAX_TURN_DEG, degrees))
        sign = 1.0 if degrees > 0 else -1.0
        result = self._turn_once(degrees)
        error = result.pop("needs", 0.0)  # Degrees still missing (+) or overshot (-).
        if abs(error) > 15:  # One corrective turn; the rate model has just been updated.
            fix = self._turn_once(sign * error, corrected=True)
            if fix.get("measured") is not None:
                result["measured"] = round(
                    result["measured"] + math.copysign(fix["measured"], error), 1
                )
                result["corrected"] = True
        return result

    def _turn_once(self, degrees: float, corrected=False) -> dict:
        sign = 1.0 if degrees > 0 else -1.0
        command = {"drive": {"linear": 0.0, "angular": sign * TURN_LEVEL}}

        def turned(a, b):
            return sign * wrap(b[0] - a[0])

        return self._run(command, abs(degrees), "turn", turned, guard=False, corrected=corrected)

    def forward(self, metres: float, start: Sense | None) -> dict:
        metres = max(-MAX_FORWARD_M, min(MAX_FORWARD_M, metres))
        limited = None
        if metres > 0 and start and start.fresh and start.clear_ahead_m is not None:
            room = max(0.0, start.clear_ahead_m - STOP_MARGIN_M)
            if room < metres:
                metres, limited = room, f"LiDAR shows an obstacle {start.clear_ahead_m:.2f} m ahead"
        if abs(metres) < 0.08:
            return dict(moved=False, measured=0.0, stopped_by=limited or "distance too small")
        sign = 1.0 if metres > 0 else -1.0
        command = {"drive": {"linear": sign * DRIVE_LEVEL, "angular": 0.0}}

        def travelled(a, b):
            dx, dz = b[1][0] - a[1][0], b[1][1] - a[1][1]
            heading = math.radians(a[0])  # Project onto the starting forward direction.
            return sign * (dx * -math.sin(heading) + dz * -math.cos(heading))

        result = self._run(command, abs(metres), "forward", travelled, guard=metres > 0)
        result.pop("needs", None)
        if limited:
            result["shortened_because"] = limited
        return result

    def _run(self, command, target, kind, measure, guard, corrected=False) -> dict:
        """One smooth timed move from the learned rate, then measured by the phone's pose."""
        reasons = self.blockers()
        if reasons:
            return dict(moved=False, measured=0.0, stopped_by="; ".join(reasons))
        origin = self.senses.pose_only()
        tracked = bool(origin and origin[2] < 2.5 and origin[3] != "unavailable")
        duration = DEAD_TIME_S + target / self.rates[kind]
        started, polled, stopped_by = time.monotonic(), time.monotonic(), None
        self.link.set_command(command)
        try:
            while (now := time.monotonic()) - started < duration:
                time.sleep(0.04)
                self.link.set_command(command)  # Renew the lease: one unbroken motion.
                telemetry, age = self.link.telemetry()
                owner = telemetry.get("control", {}).get("owner")
                if owner not in ("agent", "none", None) or self.motion._blockers(telemetry, age):
                    stopped_by = (
                        "; ".join(self.motion._blockers(telemetry, age)) or "human took over"
                    )
                    break
                if guard and tracked and now - polled >= POLL_S:
                    polled = now
                    pose = self.senses.read(render=False)
                    if (
                        pose
                        and pose.clear_ahead_m is not None
                        and pose.clear_ahead_m < STOP_MARGIN_M
                    ):
                        stopped_by = f"obstacle {pose.clear_ahead_m:.2f} m ahead"
                        break
        finally:
            self.link.release()
        ran = time.monotonic() - started
        measured = None
        if tracked:
            time.sleep(0.6)  # Let the base settle and a post-move frame arrive.
            final = self.senses.pose_only()
            if final and final[2] < 2.5:
                measured = measure(origin, final[:2])
        if measured is not None and measured > 0.15 * target and ran > DEAD_TIME_S + 0.2:
            self._learn(kind, measured / (ran - DEAD_TIME_S))
        result = dict(
            moved=True,
            requested=round(target, 2),
            measured=None if measured is None else round(measured, 2),
            unit="deg" if kind == "turn" else "m",
            measurement="phone visual-inertial pose"
            if measured is not None
            else "none: timed only",
            stopped_by=stopped_by,
            seconds=round(ran, 1),
        )
        if measured is not None and not stopped_by and not corrected:
            result["needs"] = target - measured
        return result

    def _learn(self, kind: str, rate: float) -> None:
        low, high = RATE_LIMITS[kind]
        self.rates[kind] = 0.5 * self.rates[kind] + 0.5 * max(low, min(high, rate))
        RATES_FILE.write_text(json.dumps(self.rates, indent=2) + "\n")

    def remember(self, sense: Sense | None) -> None:
        """Fold a LiDAR frame into the world grid; restart it if tracking jumped."""
        if sense is None or not sense.fresh or sense.obstacles_world is None:
            return
        jumped = self.last_position and math.dist(self.last_position, sense.position) > 4.0
        if self.grid is None or jumped or not self.grid.inside(*self.grid.index(*sense.position)):
            self.grid = planner.Grid(sense.position)
        self.last_position = sense.position
        self.grid.integrate(sense.floor_world, sense.obstacles_world)

    def go_to(self, target: tuple[float, float], on_leg=None) -> dict:
        """Drive to a world point around obstacles: plan, drive one leg, look, re-plan."""
        legs, travelled, reason, waypoints = [], 0.0, None, []
        sense = self.senses.read(render=False)
        for _ in range(40):
            if sense is None or not sense.fresh:
                reason = "the phone's view is not live, so the route cannot be followed safely"
                break
            self.remember(sense)
            remaining = math.dist(sense.position, target)
            if remaining <= ARRIVE_M:
                break
            waypoints, reason = planner.plan(self.grid, sense.position, target)
            if waypoints is None or len(waypoints) < 2:
                break
            if math.dist(waypoints[-1], sense.position) <= ARRIVE_M:
                reason = None  # As close as the obstacle around the goal allows.
                break
            nxt = waypoints[1]
            dx, dz = nxt[0] - sense.position[0], nxt[1] - sense.position[1]
            bearing = math.degrees(math.atan2(-dx, -dz))
            swing = wrap(bearing - sense.heading_deg)
            if abs(swing) > 6:
                turned = self.turn(swing)
                if not turned.get("moved"):
                    reason = turned.get("stopped_by")
                    break
                sense = self.senses.read(render=False)  # LiDAR now faces the leg: check it.
                self.remember(sense)
                check, _ = planner.plan(self.grid, sense.position, target) if sense else (None, 0)
                if check is None or len(check) < 2 or math.dist(check[1], nxt) > 0.5:
                    continue  # The turn revealed something: plan again before driving.
            leg = min(math.hypot(dx, dz), LEG_M)
            moved = self.forward(leg, sense)
            legs.append(dict(turn=round(swing), forward=moved.get("measured") or round(leg, 2)))
            travelled += moved.get("measured") or 0.0
            if on_leg:
                on_leg(len(legs))
            if not moved.get("moved") and not moved.get("stopped_by"):
                reason = "could not move"
                break
            if moved.get("stopped_by") and "obstacle" not in str(moved["stopped_by"]):
                reason = moved["stopped_by"]  # Human took over, E-STOP, link lost.
                break
            time.sleep(0.5)
            sense = self.senses.read(render=False)
        else:
            reason = "still not there after 40 legs"
        final = self.senses.read(render=False)
        left = math.dist(final.position, target) if final else None
        return dict(
            arrived=reason is None and left is not None and left <= 1.2,
            distance_left_m=None if left is None else round(left, 2),
            travelled_m=round(travelled, 2),
            legs=legs[-8:],
            stopped_by=reason,
            route=waypoints or [],
        )

    def settle_and_sense(self, before: Sense | None) -> Sense | None:
        return wait_fresh(self.senses, before.sequence if before else 0)
