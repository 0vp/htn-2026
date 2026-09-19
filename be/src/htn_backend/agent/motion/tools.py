"""Motion tool schemas for the Codex app-server; bounds here are the agent's hard limits."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .skills import Motion


class Empty(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DriveBase(Empty):
    duty: float = Field(ge=-0.3, le=0.3, description="Signed wheel duty; forward positive")
    steering_deg: float = Field(
        ge=-20,
        le=20,
        description="Servo offset: positive lowers servo angle from 90 degrees; not measured yaw",
    )
    seconds: float = Field(gt=0, le=2)


class SetArm(Empty):
    shoulder: float | None = Field(default=None, ge=-90, le=90)
    elbow: float | None = Field(default=None, ge=-120, le=120)
    wrist: float | None = Field(default=None, ge=-90, le=90)

    @model_validator(mode="after")
    def some_joint(self):
        if self.shoulder is None and self.elbow is None and self.wrist is None:
            raise ValueError("Give at least one joint angle")
        return self


class RunWinch(Empty):
    winch: int = Field(ge=1, le=3)
    direction: Literal["in", "out"]
    seconds: float = Field(gt=0, le=3)


INSTRUCTIONS = """

Motion tools (drive_base, set_arm, run_winch, stop) move the real robot base, arm and winches.
They only work while a human explicitly supervises the connected controller.
The large drive wheel stays fixed and the separate small wheel steers. Never request
differential-wheel motion or a turn in place. Check reported hardware capabilities.
Call robot_status first; if can_move is false, explain the blockers and ask the user.
Move in short steps, then observe or read robot_status before the next step.
The robot has no obstacle sensing: if you are unsure what is in front of it, do not drive.
Drive duty and steering servo offsets are commanded, not measured distance or yaw.
A completed result means the command ran for its duration, not that a place was reached.
An emergency stop stays latched until a human resets the controller. Never retry around a stop.
Call stop whenever something looks wrong.
"""

MOTION_TOOLS = {
    "robot_status": (
        Empty,
        "Read the robot's live link, supervision, E-STOP, wheel duty, arm and winch state. "
        "Check can_move and blockers before moving.",
    ),
    "drive_base": (
        DriveBase,
        "Command the single fixed drive wheel and steering servo for at most 2 seconds, "
        "then stop. Steering is NOT a chassis rotation angle; no turn-in-place skill exists. "
        "Requires supervised single_steer_v1 firmware. No calibrated distance is promised.",
    ),
    "set_arm": (
        SetArm,
        "Move arm joints to angles in degrees from neutral; omitted joints hold. Supervised "
        "only. Servos report no position, so angles are commanded, not confirmed.",
    ),
    "run_winch": (
        RunWinch,
        "Run one tentacle winch in or out for up to 3 s. Supervised only; the robot stops a "
        "winch at a pressed end stop.",
    ),
    "stop": (
        Empty,
        "Release control and stop moving now. Use whenever anything looks wrong.",
    ),
}


def call(motion: Motion, name: str, arguments: dict) -> dict:
    args = MOTION_TOOLS[name][0].model_validate(arguments)
    if name == "robot_status":
        return motion.status()
    if name == "drive_base":
        return motion.drive_base(args.duty, args.steering_deg, args.seconds)
    if name == "set_arm":
        return motion.set_arm(args.model_dump(exclude_none=True))
    if name == "run_winch":
        return motion.run_winch(args.winch, args.direction, args.seconds)
    return motion.stop()
