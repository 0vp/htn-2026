"""Bounded, supervised motion primitives for the robot base, arm and winches.

Every skill blocks until its command has run for its duration or something stopped it, and
reports what the robot's own telemetry said. Encoder counts are uncalibrated;
results describe commanded duty and servo offsets, not measured distance or yaw.
"""

import math
import time

from .link import RobotLink

SERVO_DEG_PER_S = 60  # robot/src/config.h slew limit
MAX_SECONDS = 12.0
TELEMETRY_STALE_S = 1.0
GRANT_TIMEOUT_S = 0.8
POLL_S = 0.05
DRIVETRAIN = "bts7960_diff_v2"
MAX_LEVEL = 0.5  # Share of the calibrated wheel range; see robot/README.md

NOT_MEASURED = (
    "Only calibrated wheel levels were commanded; distance and yaw are not measured (no encoders), "
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
            drivetrain=telemetry.get("drivetrain"),
            motor_duty=telemetry.get("motor_duty"),
            uptime_ms=telemetry.get("uptime_ms"),
            reset_reason=telemetry.get("reset_reason"),
            steering_deg=telemetry.get("steering_deg"),
            steering_feedback=telemetry.get("steering_feedback"),
            encoder_ticks=telemetry.get("encoder_ticks"),
            odometry_calibrated=telemetry.get("odometry_calibrated", False),
            capabilities=telemetry.get("capabilities", {}),
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
        if telemetry.get("drivetrain") != DRIVETRAIN:
            reasons.append(f"drivetrain_mismatch: expected {DRIVETRAIN} via robot/scripts/drive.py")
        if control.get("estop", True):
            reasons.append("estop_latched: a human must inspect and reset the controller")
        if not control.get("supervised", False):
            reasons.append("not_supervised: human supervision must be enabled at the controller")
        if control.get("owner") not in (None, "none", "agent"):
            reasons.append("human_in_control: someone is driving manually")
        return reasons

    def drive_base(self, linear: float, angular: float, seconds: float) -> dict:
        if (
            not all(math.isfinite(v) for v in (linear, angular, seconds))
            or abs(linear) > MAX_LEVEL
            or abs(angular) > MAX_LEVEL
            or not 0 < seconds <= 2
        ):
            return dict(state="rejected", dispatched=False, reason="invalid_bounded_base_command")
        return self._run(
            {"drive": {"linear": linear, "angular": angular}},
            seconds,
            dict(skill="drive_base", linear=linear, angular=angular, seconds=seconds),
            estimate={
                "note": "Open loop. Floor calibration at level 0.3 measured roughly 55 deg/s "
                "turn in place (includes ramp-up); linear speed is not measured."
            },
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
        released = self.link.release()
        self._wait_until_still()
        return dict(skill="stop", release_sent=released, status=self.status())

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

        if telemetry.get("capabilities", {}).get(request["skill"]) is not True:
            return dict(
                request=request,
                state="blocked",
                dispatched=False,
                reasons=["hardware_capability_unavailable"],
            )
        start_counts = telemetry.get("encoder_ticks")
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
                    stopped_by = "estop: the controller reported an emergency stop"
                elif not control.get("supervised"):
                    stopped_by = "supervision_lost: the controller withdrew supervision"
                elif control.get("owner") == "agent":
                    granted = True
                elif granted:
                    stopped_by = f"control_revoked (owner now {control.get('owner')})"
                elif elapsed > GRANT_TIMEOUT_S:
                    stopped_by = f"control_not_granted (owner {control.get('owner')})"
                if stopped_by or elapsed >= seconds:
                    break
                self.link.set_command(command)  # Renew only after checking live supervision.
        finally:
            released = self.link.release()

        elapsed = time.monotonic() - started
        settled = self._wait_until_still()
        end_counts = self.link.telemetry()[0].get("encoder_ticks")
        if stopped_by is None:
            if not granted:
                stopped_by = "control_not_granted"
            elif not released:
                stopped_by = "release_not_sent"
            elif not settled:
                stopped_by = "stop_not_reported"
        result = dict(
            request=request,
            state="completed" if stopped_by is None else "interrupted",
            dispatched=granted,
            physical_success=False,
            stop_evidence="reported zero drive duty; not measured base velocity",
            stopped_by=stopped_by,
            commanded_seconds=round(seconds, 2),
            ran_seconds=round(elapsed, 2),
            release_sent=released,
            robot_reports_stopped=settled,
            encoder_counts_delta=end_counts - start_counts
            if isinstance(start_counts, int) and isinstance(end_counts, int)
            else None,
        )
        if stopped_by is None:
            result["estimate"] = estimate
        if request["skill"] == "drive_base":
            result["measurement"] = NOT_MEASURED
        return result

    def _wait_until_still(self) -> bool:
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            telemetry, age = self.link.telemetry()
            values = [telemetry.get("motor_duty")]
            if age < TELEMETRY_STALE_S and all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and abs(value) < 0.01
                for value in values
            ):
                return True
            time.sleep(POLL_S)
        return False
