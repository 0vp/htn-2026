"""Smooth, measured moves: one continuous command per move, checked by the phone's pose.

The phone's ARKit pose fuses its gyroscope, accelerometer and camera, but reaches the laptop
~0.5-1 s late: too late to stop on (a 60 degree turn overshot to 153). So a move is timed from a
learned rate (deg/s, m/s), streamed as one steady command the firmware ramps, then measured
from the pose. Each measurement refines the rate, and a turn that lands off gets one
corrective turn. Forward moves still poll LiDAR and stop if the lane closes.
"""

import json
import math
import threading
import time
from pathlib import Path

from ..motion.link import RobotLink
from ..motion.skills import Motion
from .senses.perception import Sense, Senses, wait_fresh

TURN_LEVEL, DRIVE_LEVEL = 0.3, 0.3
# Starting rates at these levels; every measured move refines them (robot/scripts/rates.json).
DEFAULT_RATES = {"turn": 48.0, "forward": 0.33}  # deg/s, m/s
RATE_LIMITS = {"turn": (32.0, 75.0), "forward": (0.22, 0.55)}  # Around the floor calibration.
LEARN_FROM = {"turn": 30.0, "forward": 0.5}  # Short moves are mostly ramp: do not learn from them.
RATES_FILE = Path(__file__).resolve().parents[5] / "robot/scripts/rates.json"
DEAD_TIME_S = 0.25  # Ramp-up before the base is really moving.
# Measured on the floor: after the wheels are released the base still coasts this much, whatever
# the size of the move (a 45 degree turn became 56, a 90 became 100).
COAST = {"turn": 11.0, "forward": 0.05}
# Lane keeping. Pose is ~0.5 s old, so the heading gain is kept low enough not to oscillate:
# a 10 degree error asks for ~10 deg/s of correction.
HEADING_GAIN = 0.006  # drive level per degree of heading error
MAX_STEER = 0.12
OPEN_SIDE_M = 1.3  # Beyond this a side counts as open and does not pull the robot.
CENTRE_GAIN = 14.0  # Degrees of lean per metre of left/right imbalance
MAX_LEAN_DEG = 12.0
REAR_IR = (0, 3)  # Positions of the rear-facing sensors in the firmware's ir_raw list.
STOP_MARGIN_M = 0.65  # From the phone at the centre: leaves ~0.25 m between hull and obstacle.
MAX_TURN_DEG, MAX_FORWARD_M, MAX_REVERSE_M = 180.0, 3.0, 0.4


def wrap(degrees: float) -> float:
    return (degrees + 180.0) % 360.0 - 180.0


class Navigator:
    def __init__(self, link: RobotLink, senses: Senses):
        self.link, self.senses, self.motion = link, senses, Motion(link)
        # Rear IR obstacle sensors (robot/README.md): output goes LOW when something is within a
        # few tens of cm. One reads LOW permanently, so a sensor only counts once it has been
        # seen HIGH this session, which proves it is wired and can tell the difference.
        self.ir_proven = [False] * 4
        self.rates = dict(DEFAULT_RATES)
        if RATES_FILE.exists():
            saved = json.loads(RATES_FILE.read_text())
            for kind, (low, high) in RATE_LIMITS.items():
                if low <= saved.get(kind, 0) <= high:  # Ignore a file poisoned by bad runs.
                    self.rates[kind] = saved[kind]

    def blockers(self) -> list[str]:
        return self.motion.blockers()

    def rear_blocked(self, telemetry=None) -> bool | None:
        """True if a proven rear IR sensor sees something, None if no sensor is proven yet."""
        if telemetry is None:
            telemetry, _ = self.link.telemetry()
        raw = telemetry.get("ir_raw") or []
        for index, value in enumerate(raw[:4]):
            if value == 1:
                self.ir_proven[index] = True
        if not any(self.ir_proven):
            return None
        return any(
            proven and value == 0 for proven, value in zip(self.ir_proven, raw, strict=False)
        )

    def stop(self) -> None:
        self.link.release()

    def turn(self, degrees: float) -> dict:
        degrees = max(-MAX_TURN_DEG, min(MAX_TURN_DEG, degrees))
        sign = 1.0 if degrees > 0 else -1.0
        if abs(degrees) > 100:  # Two halves: a single long timed turn is where errors grow.
            first = self.turn(degrees / 2)
            if not first.get("moved") or first.get("stopped_by"):
                return first
            second = self.turn(degrees / 2)
            if first.get("measured") is not None and second.get("measured") is not None:
                second["measured"] = round(first["measured"] + second["measured"], 1)
            second["requested"] = round(abs(degrees), 1)
            return second
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

    def _turn_once(self, degrees: float, corrected=False, quick=False) -> dict:
        sign = 1.0 if degrees > 0 else -1.0
        command = {"drive": {"linear": 0.0, "angular": sign * TURN_LEVEL}}

        def turned(a, b):
            return sign * wrap(b[0] - a[0])

        return self._run(
            command, abs(degrees), "turn", turned, guard=False, corrected=corrected, quick=quick
        )

    def forward(self, metres: float, start: Sense | None, quick=False) -> dict:
        metres = max(-MAX_REVERSE_M, min(MAX_FORWARD_M, metres))
        limited = None
        if metres > 0 and start and start.fresh and start.clear_ahead_m is not None:
            room = max(0.0, start.clear_ahead_m - STOP_MARGIN_M)
            if room < metres:
                metres, limited = room, f"LiDAR shows an obstacle {start.clear_ahead_m:.2f} m ahead"
        if metres < 0 and self.rear_blocked() is not False:
            metres, limited = 0.0, "cannot reverse: the rear IR sensors are not reporting clear"
        if abs(metres) < 0.08:
            return dict(moved=False, measured=0.0, stopped_by=limited or "distance too small")
        sign = 1.0 if metres > 0 else -1.0
        command = {"drive": {"linear": sign * DRIVE_LEVEL, "angular": 0.0}}

        def travelled(a, b):
            dx, dz = b[1][0] - a[1][0], b[1][1] - a[1][1]
            heading = math.radians(a[0])  # Project onto the starting forward direction.
            return sign * (dx * -math.sin(heading) + dz * -math.cos(heading))

        result = self._run(
            command, abs(metres), "forward", travelled, guard=metres > 0, quick=quick
        )
        result.pop("needs", None)
        if limited:
            result["shortened_because"] = limited
        return result

    def _run(self, command, target, kind, measure, guard, corrected=False, quick=False) -> dict:
        """One smooth timed move from the learned rate, then measured by the phone's pose."""
        reasons = self.blockers()
        if reasons:
            return dict(moved=False, measured=0.0, stopped_by="; ".join(reasons))
        origin = self.senses.pose_only()
        tracked = bool(origin and origin[2] < 2.5 and origin[3] != "unavailable")
        duration = DEAD_TIME_S + max(target - COAST[kind], 0.0) / self.rates[kind]
        duration = max(duration, 0.3)
        started, stopped_by = time.monotonic(), None
        reversing = command["drive"]["linear"] < 0
        # LiDAR is watched from a second thread: a frame download takes ~0.5 s, and doing it in
        # the command loop let the 0.25 s command lease lapse, so moves stuttered and measured
        # short, which then taught the rate model that the robot was slow.
        blocked, moving = [], threading.Event()
        moving.set()
        steer = [0.0] if guard and tracked and kind == "forward" else None
        if guard and tracked:
            hold = origin[0] if steer is not None else None
            threading.Thread(
                target=self._guard, args=(moving, blocked, steer, hold), daemon=True
            ).start()
        self.link.set_command(command)
        try:
            while time.monotonic() - started < duration:
                time.sleep(0.04)
                if steer is not None:  # Lane keeping: blend the latest steering into the drive.
                    command = {"drive": dict(command["drive"], angular=steer[0])}
                self.link.set_command(command)  # Renew the lease: one unbroken motion.
                telemetry, age = self.link.telemetry()
                owner = telemetry.get("control", {}).get("owner")
                if owner not in ("agent", "none", None) or self.motion._blockers(telemetry, age):
                    stopped_by = (
                        "; ".join(self.motion._blockers(telemetry, age)) or "human took over"
                    )
                    break
                if blocked:
                    stopped_by = blocked[0]
                    break
                if reversing and self.rear_blocked(telemetry):
                    stopped_by = "rear IR sensor sees something behind"
                    break
        finally:
            moving.clear()
            self.link.release()
        ran = time.monotonic() - started
        final = None if quick else (self._settled_pose() if tracked else None)
        measured = measure(origin, final[:2]) if final else None
        if measured is not None and kind == "turn" and measured < -20:
            measured += 360.0  # Overshot past half a circle: the angle wrapped around.
        clean = measured is not None and not stopped_by and target >= LEARN_FROM[kind]
        if clean and 0.4 <= measured / target <= 2.5 and ran > DEAD_TIME_S + 0.3:
            self._learn(kind, (measured - COAST[kind]) / (ran - DEAD_TIME_S))
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

    def _guard(self, moving, blocked, steer=None, hold_deg=None) -> None:
        """Runs beside a straight leg: stops it when the lane closes and, a few times a second,
        steers it. Steering is lane keeping as a driver does it: hold the heading the leg
        started on (the wheels are unequal, so an open-loop leg curves into walls), and when a
        wall or doorframe is close on one side, aim a few degrees toward the roomier side."""
        while moving.is_set():
            pose = self.senses.read(render=False)
            if pose and pose.fresh and pose.clear_ahead_m is not None:
                if pose.clear_ahead_m < STOP_MARGIN_M:
                    blocked.append(f"obstacle {pose.clear_ahead_m:.2f} m ahead")
                    return
                if steer is not None and hold_deg is not None:
                    left = pose.wall_left_m if pose.wall_left_m is not None else OPEN_SIDE_M
                    right = pose.wall_right_m if pose.wall_right_m is not None else OPEN_SIDE_M
                    lean = 0.0
                    if min(left, right) < OPEN_SIDE_M:
                        lean = max(-MAX_LEAN_DEG, min(MAX_LEAN_DEG, CENTRE_GAIN * (left - right)))
                    error = wrap(hold_deg + lean - pose.heading_deg)
                    steer[0] = max(-MAX_STEER, min(MAX_STEER, HEADING_GAIN * error))
            time.sleep(0.05)

    def _settled_pose(self):
        """The pose once the base has really stopped: two fresh frames that agree.

        A frame from before the stop under-measures the move, and under-measuring is what made
        the rate model run away, so wait (up to ~3 s) rather than trust the first frame.
        """
        time.sleep(0.5)
        previous, deadline = None, time.monotonic() + 3.0
        while time.monotonic() < deadline:
            pose = self.senses.pose_only()
            if pose and pose[2] < 1.5:
                still = previous and abs(wrap(pose[0] - previous[0])) < 1.0
                if still and math.dist(pose[1], previous[1]) < 0.03:
                    return pose
                previous = pose
            time.sleep(0.2)
        return previous

    def _learn(self, kind: str, rate: float) -> None:
        """Nudge the rate toward a clean measurement; never far from the floor calibration."""
        low, high = RATE_LIMITS[kind]
        rate = max(low, min(high, rate))
        self.rates[kind] = round(0.7 * self.rates[kind] + 0.3 * rate, 3)
        RATES_FILE.write_text(json.dumps(self.rates, indent=2) + "\n")

    def face(self, heading_deg: float) -> None:
        """Turn back to a heading seen earlier (e.g. where the fast eye spotted the target)."""
        pose = self.senses.pose_only()
        if pose and abs(swing := wrap(heading_deg - pose[0])) > 8:
            self.turn(swing)

    def settle_and_sense(self, before: Sense | None) -> Sense | None:
        return wait_fresh(self.senses, before.sequence if before else 0)
