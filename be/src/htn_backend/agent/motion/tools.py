"""Motion tool schemas for the Codex app-server; bounds here are the agent's hard limits."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .skills import Motion


class Empty(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Drive(Empty):
    distance_m: float = Field(ge=-1.0, le=1.0, description="Forward positive, reverse negative")
    speed: float = Field(default=0.2, ge=0.05, le=0.3, description="Fraction of full motor duty")


class Turn(Empty):
    degrees: float = Field(ge=-180, le=180, description="Left (counter-clockwise) positive")
    speed: float = Field(default=0.2, ge=0.05, le=0.3)


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


MOTION_TOOLS = {
    "robot_status": (
        Empty,
        "Read the robot's live link, supervision, E-STOP, wheel duty, arm and winch state. "
        "Check can_move and blockers before moving.",
    ),
    "drive": (
        Drive,
        "Drive straight up to 1 m at up to 30% speed, then stop. Only works while a human "
        "supervises in badge AUTO mode. Distance is estimated from time, not measured.",
    ),
    "turn": (
        Turn,
        "Turn in place up to 180 degrees (left positive), then stop. Supervised only; the "
        "angle is estimated from time, not measured.",
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
    if name == "drive":
        return motion.drive(args.distance_m, args.speed)
    if name == "turn":
        return motion.turn(args.degrees, args.speed)
    if name == "set_arm":
        return motion.set_arm(args.model_dump(exclude_none=True))
    if name == "run_winch":
        return motion.run_winch(args.winch, args.direction, args.seconds)
    return motion.stop()
