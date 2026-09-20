"""Process-wide motion link for agent runs started inside the server (voice commands)."""

import os
import threading

from .link import RobotLink
from .skills import Motion

_lock = threading.Lock()
_motion: Motion | None = None


def server_motion() -> Motion | None:
    """Motion over HTN_ROBOT_URL (normally the loopback relay), or None when not configured."""
    global _motion
    url = os.environ.get("HTN_ROBOT_URL")
    if not url:
        return None
    with _lock:
        if _motion is None:
            link = RobotLink(url, os.environ.get("HTN_ROBOT_TOKEN", ""))
            link.start()
            _motion = Motion(link)
        return _motion
