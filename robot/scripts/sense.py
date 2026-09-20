"""Motion sensing from the laptop riding on the robot, using its camera as a visual gyro.

macOS gives no unprivileged access to the MacBook's accelerometer/gyro (the Apple SPU HID
device needs root), so yaw comes from image motion instead: tracked features are fitted with a
similarity transform per frame. Horizontal shift / focal length = yaw; scale change = motion
along the camera axis (unitless, sign only is trusted).

OpenCV frames are NOT mirrored (only preview apps mirror), so: robot turns left (CCW from above)
-> scene shifts right -> positive yaw here.
"""

import math
import threading
import time

import cv2
import numpy as np

HFOV_DEG = 54.0  # MacBook FaceTime HD camera, approximate; scales yaw magnitudes only.


class VisualGyro:
    def __init__(self, index=0, width=640):
        self.capture = cv2.VideoCapture(index)
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        ok, frame = self.capture.read()
        if not ok:
            raise RuntimeError("Camera unavailable (grant the terminal camera permission)")
        self.width = width
        self.focal = width / (2 * math.tan(math.radians(HFOV_DEG / 2)))
        self.yaw_deg, self.log_scale, self.quality = 0.0, 0.0, 0.0
        self.lock, self.alive = threading.Lock(), True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _gray(self, frame):
        height = int(frame.shape[0] * self.width / frame.shape[1])
        return cv2.cvtColor(cv2.resize(frame, (self.width, height)), cv2.COLOR_BGR2GRAY)

    def _run(self):
        previous = None
        while self.alive:
            ok, frame = self.capture.read()
            if not ok:
                continue
            gray = self._gray(frame)
            if previous is not None:
                self._step(previous, gray)
            previous = gray

    def _step(self, previous, gray):
        points = cv2.goodFeaturesToTrack(previous, 300, 0.01, 8)
        if points is None or len(points) < 20:
            self.quality = 0.0
            return
        moved, status, _ = cv2.calcOpticalFlowPyrLK(previous, gray, points, None)
        keep = status.ravel() == 1
        if keep.sum() < 20:
            self.quality = 0.0
            return
        center = np.array([gray.shape[1] / 2, gray.shape[0] / 2], np.float32)
        a, b = points[keep].reshape(-1, 2) - center, moved[keep].reshape(-1, 2) - center
        matrix, inliers = cv2.estimateAffinePartial2D(a, b, method=cv2.RANSAC)
        if matrix is None:
            return
        scale = math.hypot(matrix[0, 0], matrix[1, 0])
        with self.lock:
            self.yaw_deg += math.degrees(math.atan2(matrix[0, 2], self.focal))
            self.log_scale += math.log(scale)
            self.quality = float(inliers.mean())

    def read(self):
        with self.lock:
            return self.yaw_deg, self.log_scale

    def close(self):
        self.alive = False
        self.thread.join(timeout=1)
        self.capture.release()


def settle(gyro, seconds=0.6):
    time.sleep(seconds)
    return gyro.read()
