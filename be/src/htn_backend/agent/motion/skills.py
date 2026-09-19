"""Bounded, supervised motion primitives for the robot base, arm and winches.

Every skill blocks until its command has run for its duration or something stopped it, and
reports what the robot's own telemetry said. Distances and angles are estimated from time
(the encoders are uncalibrated), so results describe commanded motion, not measured motion.
"""

import math
import time

from .link import RobotLink

# 40 RPM gearbox, 95 mm wheels, no load; a loaded robot is slower, so estimates run long.
WHEEL_MPS_AT_FULL_DUTY = 40 / 60 * math.pi * 0.095
TRACK_M = 0.30  # CALIBRATE: distance between the drive wheels
SERVO_DEG_PER_S = 60  # robot/src/config.h slew limit
MAX_SECONDS = 12.0
TELEMETRY_STALE_S = 1.0
GRANT_TIMEOUT_S = 0.8
POLL_S = 0.05

NOT_MEASURED = (
    "Motion is estimated from commanded speed and time; wheel encoders are not calibrated, "
    "so the robot may have moved less (load, slip) or been stopped by an obstacle."
)


class Motion:
    def __init__(self, link: RobotLink):
        self.link = link

    def status(self) -> dict:
        telemetry, age = self.link.telemetry()
        control = telemetry.get("control", {})
        return dict(
            link="connected" if self.link.connected else "disconnected",
            telemetry_age_s=None if math.isinf(age) else round(age, 2),
            owner=control.get("owner"),
            supervised_by_badge=control.get("supervised", False),
            estop=control.get("estop", True),
            duty=telemetry.get("duty"),
            servo_deg=telemetry.get("servoDeg"),
            winch_position=telemetry.get("winchPos"),
            end_stops=telemetry.get("limits"),
            pack_volts=telemetry.get("packVolts"),
            can_move=not self._blockers(telemetry, age),
            blockers=self._blockers(telemetry, age),
        )

    def _blockers(self, telemetry: dict, age: float) -> list[str]:
        if not self.link.connected:
            return ["robot_link_down: the laptop cannot reach the robot"]
        if age > TELEMETRY_STALE_S:
            return ["robot_silent: no recent telemetry"]
        control = telemetry.get("control", {})
        reasons = []
        if control.get("estop", True):
            reasons.append("estop_latched: a human must clear it on the badge")
        if not control.get("supervised", False):
            reasons.append("not_supervised: ask the user to arm AUTO mode on the badge")
        if control.get("owner") not in (None, "none", "agent"):
            reasons.append("human_in_control: someone is driving manually")
        return reasons

    def drive(self, distance_m: float, speed: float) -> dict:
        seconds = abs(distance_m) / (speed * WHEEL_MPS_AT_FULL_DUTY)
        duty = math.copysign(speed, distance_m)
        return self._run(
            {"drive": {"left": duty, "right": duty}},
            seconds,
            dict(skill="drive", distance_m=distance_m, speed=speed),
            estimate={"distance_m": distance_m},
        )

    def turn(self, degrees: float, speed: float) -> dict:
        # Positive degrees turn left (counter-clockwise seen from above): wheels run opposite.
        arc = math.radians(abs(degrees)) * TRACK_M / 2
        seconds = arc / (speed * WHEEL_MPS_AT_FULL_DUTY)
        duty = math.copysign(speed, degrees)
        return self._run(
            {"drive": {"left": -duty, "right": duty}},
            seconds,
            dict(skill="turn", degrees=degrees, speed=speed),
            estimate={"degrees": degrees},
        )

    def set_arm(self, target: dict[str, float]) -> dict:
        telemetry, _ = self.link.telemetry()
        current = telemetry.get("servoDeg") or {}
        joints = {j: target.get(j, current.get(j, 0.0)) for j in ("shoulder", "elbow", "wrist")}
        travel = max(abs(joints[j] - current.get(j, 0.0)) for j in joints)
        return self._run(
            {"arm": joints},
            travel / SERVO_DEG_PER_S + 0.3,
            dict(skill="set_arm", **joints),
            estimate={"note": "servos report no position; angles are commanded, not measured"},
        )

    def run_winch(self, winch: int, direction: str, seconds: float) -> dict:
        winches = [0, 0, 0]
        winches[winch - 1] = -1 if direction == "in" else 1
        return self._run(
            {"winch": winches},
            seconds,
            dict(skill="run_winch", winch=winch, direction=direction, seconds=seconds),
            estimate={"note": "the robot refuses to drive a winch into a pressed end stop"},
        )

    def stop(self) -> dict:
        self.link.set_command(None)
        time.sleep(0.3)
        return dict(skill="stop", released=True, status=self.status())

    def _run(self, command: dict, seconds: float, request: dict, estimate: dict) -> dict:
        if seconds > MAX_SECONDS:
            return dict(
                request=request,
                state="rejected",
                reason=f"would take {seconds:.1f} s; split into moves under {MAX_SECONDS:.0f} s",
            )
        telemetry, age = self.link.telemetry()
        blockers = self._blockers(telemetry, age)
        if blockers:
            return dict(request=request, state="blocked", dispatched=False, reasons=blockers)

        start_counts = telemetry.get("encoders")
        started = time.monotonic()
        granted, stopped_by = False, None
        self.link.set_command(command)
        try:
            while True:
                time.sleep(POLL_S)
                elapsed = time.monotonic() - started
                telemetry, age = self.link.telemetry()
                control = telemetry.get("control", {})
                if not self.link.connected:
                    stopped_by = "robot_link_lost"
                elif age > TELEMETRY_STALE_S:
                    stopped_by = "robot_silent"
                elif control.get("estop"):
                    stopped_by = "estop: a human pressed stop on the badge"
                elif not control.get("supervised"):
                    stopped_by = "supervision_lost: the badge left AUTO"
                elif control.get("owner") == "agent":
                    granted = True
                elif granted:
                    stopped_by = f"control_revoked (owner now {control.get('owner')})"
                elif elapsed > GRANT_TIMEOUT_S:
                    stopped_by = f"control_not_granted (owner {control.get('owner')})"
                if stopped_by or elapsed >= seconds:
                    break
        finally:
            self.link.set_command(None)

        elapsed = time.monotonic() - started
        settled = self._wait_until_still()
        end_counts = self.link.telemetry()[0].get("encoders")
        result = dict(
            request=request,
            state="completed" if stopped_by is None else "interrupted",
            dispatched=granted,
            stopped_by=stopped_by,
            commanded_seconds=round(seconds, 2),
            ran_seconds=round(elapsed, 2),
            robot_reports_stopped=settled,
            encoder_counts_delta={
                side: end_counts[side] - start_counts[side] for side in ("left", "right")
            }
            if start_counts and end_counts
            else None,
        )
        if stopped_by is None:
            result["estimate"] = estimate
        if request["skill"] in ("drive", "turn"):
            result["measurement"] = NOT_MEASURED
        return result

    def _wait_until_still(self) -> bool:
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            telemetry, age = self.link.telemetry()
            duty = telemetry.get("duty") or {}
            if age < TELEMETRY_STALE_S and not duty.get("left") and not duty.get("right"):
                return True
            time.sleep(POLL_S)
        return False
