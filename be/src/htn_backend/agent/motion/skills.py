"""Whether the base may move right now, from its own telemetry.

The moves themselves live in agent/embodied (navigator.py); this is the gate they all check:
link up, telemetry fresh, right firmware, no E-STOP, supervised, and no human at the keys.
"""

import math

from .link import RobotLink

TELEMETRY_STALE_S = 1.0
DRIVETRAIN = "bts7960_diff_v2"


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

    def blockers(self) -> list[str]:
        telemetry, age = self.link.telemetry()
        return self._blockers(telemetry, age)

    def stop(self) -> dict:
        released = self.link.release()
        return dict(release_sent=released, status=self.status())
