"""Quarter-turn inference orientation from ARKit gravity, without rotating sensor geometry."""

import numpy as np

from ..capture.frame import FrameHeader


def upright_quarter_turns(header: FrameHeader) -> int:
    if header.camera_convention != "arkit":
        return 0
    pose = np.asarray(header.camera_to_world).reshape(4, 4, order="F")
    # np.rot90(k): new visual up is old +Y, +X, -Y, or -X in ARKit coordinates.
    scores = [pose[1, 1], pose[1, 0], -pose[1, 1], -pose[1, 0]]
    if max(scores) < 0.25:  # Looking nearly straight up/down: roll is ambiguous.
        return 0
    return int(np.argmax(scores))
