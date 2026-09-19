"""Public room request contracts."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

RoomID = Annotated[str, StringConstraints(pattern=r"^[A-F0-9]{4}$")]
DeviceID = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class CreateRoom(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name = "Room"


class JoinRoom(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: DeviceID
    name: Name = Field(default="iPhone")
