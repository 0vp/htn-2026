"""Smooth, measured moves: one continuous command per move, stopped by the phone's pose.

A move streams a single steady wheel command (the firmware ramps it) while the ARKit pose is
polled, and ends when the measured turn/distance reaches the target, the LiDAR lane closes,
a human takes over, or time runs out. Pose arrives ~0.5 s late, so the stop is led by the
rate measured during the move. Without fresh pose it falls back to calibrated timing.
"""

import math
import time

from ..motion.link import RobotLink
from ..motion.skills import Motion
from .perception import Sense, Senses, wait_fresh

TURN_LEVEL, DRIVE_LEVEL = 0.3, 0.3
TURN_DEG_PER_S = 50.0  # Floor calibration at level 0.3 (robot/README.md); only a fallback.
DRIVE_M_PER_S = 0.35  # Rough guess; pose feedback replaces it whenever tracking is live.
STOP_MARGIN_M = 0.45
POLL_S = 0.3
MAX_TURN_DEG, MAX_FORWARD_M = 180.0, 2.0


def wrap(degrees: float) -> float:
    return (degrees + 180.0) % 360.0 - 180.0


class Navigator:
    def __init__(self, link: RobotLink, senses: Senses):
        self.link, self.senses, self.motion = link, senses, Motion(link)

    def blockers(self) -> list[str]:
        telemetry, age = self.link.telemetry()
        return self.motion._blockers(telemetry, age)

    def stop(self) -> None:
        self.link.release()

    def turn(self, degrees: float) -> dict:
        degrees = max(-MAX_TURN_DEG, min(MAX_TURN_DEG, degrees))
        sign = 1.0 if degrees > 0 else -1.0
        command = {"drive": {"linear": 0.0, "angular": sign * TURN_LEVEL}}
        return self._run(
            command,
            abs(degrees),
            "turn",
            lambda a, b: sign * wrap(b[0] - a[0]),
            abs(degrees) / TURN_DEG_PER_S + 0.4,
            guard=False,
        )

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

        result = self._run(
            command,
            abs(metres),
            "forward",
            travelled,
            abs(metres) / DRIVE_M_PER_S + 0.5,
            guard=metres > 0,
        )
        if limited:
            result["shortened_because"] = limited
        return result

    def _run(self, command, target, kind, measure, fallback_s, guard) -> dict:
        reasons = self.blockers()
        if reasons:
            return dict(moved=False, measured=0.0, stopped_by="; ".join(reasons))
        origin = self.senses.pose_only()
        tracked = bool(origin and origin[2] < 2.5 and origin[3] != "unavailable")
        budget = fallback_s * (2.5 if tracked else 1.0) + 1.0
        started, progress, rate, stopped_by = time.monotonic(), 0.0, 0.0, None
        last_progress_at, polled = started, started
        self.link.set_command(command)
        try:
            while True:
                time.sleep(0.05)
                now = time.monotonic()
                self.link.set_command(command)  # Renew the lease: one unbroken motion.
                telemetry, age = self.link.telemetry()
                if (
                    self.motion._blockers(telemetry, age)
                    and telemetry.get("control", {}).get("owner") != "agent"
                ):
                    stopped_by = "; ".join(self.motion._blockers(telemetry, age))
                    break
                if tracked and now - polled >= POLL_S:
                    polled = now
                    pose = self.senses.read(render=False)
                    if pose:
                        measured = measure(origin, (pose.heading_deg, pose.position))
                        if measured > progress + 1e-3:
                            rate = (measured - progress) / max(now - last_progress_at, 0.05)
                            progress, last_progress_at = measured, now
                        if (
                            guard
                            and pose.clear_ahead_m is not None
                            and pose.clear_ahead_m < STOP_MARGIN_M
                        ):
                            stopped_by = f"obstacle {pose.clear_ahead_m:.2f} m ahead"
                            break
                        if progress + rate * (pose.age_s + 0.25) >= target:
                            break
                if not tracked and now - started >= fallback_s:
                    break
                if now - started >= budget:
                    stopped_by = "time limit reached before the target was measured"
                    break
        finally:
            self.link.release()
        final = None
        if tracked:
            time.sleep(0.7)  # Let the robot settle and a post-move frame arrive.
            final = self.senses.pose_only()
        measured = measure(origin, final[:2]) if tracked and final else None
        unit = "deg" if kind == "turn" else "m"
        return dict(
            moved=True,
            requested=round(target, 2),
            measured=None if measured is None else round(measured, 2),
            unit=unit,
            measurement="phone ARKit pose"
            if measured is not None
            else "none: timed open-loop (pose not live)",
            stopped_by=stopped_by,
            seconds=round(time.monotonic() - started, 1),
        )

    def settle_and_sense(self, before: Sense | None) -> Sense | None:
        return wait_fresh(self.senses, before.sequence if before else 0)
