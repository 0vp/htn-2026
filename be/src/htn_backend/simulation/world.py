"""MuJoCo physics and feedback; no teleports or grasp welds during actions."""

import io
import math

import mujoco
import numpy as np
from PIL import Image

from .control.safety import check as check_motion
from .mechanics.kinematics import arm_ik
from .model import scene


class World:
    def __init__(self, seed=0, layout="detour"):
        xml, self.tables, self.obstacles = scene(seed, layout)
        self.model = mujoco.MjModel.from_xml_string(xml)
        self.data = mujoco.MjData(self.model)
        self.renderer = None
        self.cancelled = False
        self.failed = False
        self.held = None
        self.path_length = 0.0
        self.collisions = 0
        self.trace = []
        self.callback = lambda: None
        self.act = {self.model.actuator(i).name: i for i in range(self.model.nu)}
        initial = arm_ik(0.19, 0.88)
        for name, value in zip(("shoulder", "elbow", "wrist"), initial, strict=True):
            self.data.joint(name).qpos[0] = value
            self.data.ctrl[self.act[name]] = value
        self.command_speed = 0.0
        self.command_deadline = 0.0
        self.safety_stop = None
        self.command_steering = 0.0
        self.step(1)

    @property
    def pose(self):
        matrix = self.data.body("base").xmat.reshape(3, 3)
        return np.array([*self.data.body("base").xpos[:2], math.atan2(matrix[1, 0], matrix[0, 0])])

    @property
    def block(self):
        return self.data.body("blue_block").xpos.copy()

    def contacts(self):
        pairs = set()
        for c in self.data.contact[: self.data.ncon]:
            if c.dist <= 0:
                names = tuple(
                    self.model.geom(int(g)).name
                    or self.model.body(int(self.model.geom_bodyid[g])).name
                    for g in (c.geom1, c.geom2)
                )
                pairs.add(frozenset(names))
        return pairs

    def grasp_contacts(self):
        pairs = self.contacts()
        return all(
            any(
                "blue_block" in pair and any(name.startswith(side + "_segment") for name in pair)
                for pair in pairs
            )
            for side in ("left", "right")
        )

    def drive_world(self, vx, vy, omega):
        # One steering contact cannot independently command chassis yaw. Track
        # a world translation direction; report the resulting measured yaw.
        self.command_deadline = float(self.data.time) + 0.2
        speed = math.hypot(vx, vy)
        if speed < 1e-6:
            self.data.ctrl[self.act["wheel"]] = 0
            return
        direction = angle(math.atan2(vy, vx) - self.pose[2])
        measured_steering = self.data.joint("steering").qpos[0]
        # Choose the closest equivalent rolling direction. Hysteresis through
        # actuator travel cost prevents forward/reverse chatter around 90 degrees.
        candidates = []
        for sign, desired in ((1, direction), (-1, angle(direction - math.pi))):
            steering = float(np.clip(desired, -1.5, 1.5))
            mismatch = abs(angle(desired - steering))
            if mismatch < 0.5:
                cost = (steering - measured_steering) ** 2 + 0.8 * mismatch**2
                candidates.append((cost, sign, steering))
        if not candidates:
            self.data.ctrl[self.act["wheel"]] = 0
            return
        _, sign, steering = min(candidates)
        self.command_speed = float(np.clip(sign * speed, -0.25, 0.25))
        self.command_steering = steering
        self.data.ctrl[self.act["steering"]] = self.command_steering
        # Let the steering joint align before applying traction.
        error = abs(self.data.joint("steering").qpos[0] - self.command_steering)
        self.data.ctrl[self.act["wheel"]] = (
            self.command_speed / 0.095 * math.cos(error) ** 2 if error < 0.3 else 0
        )

    def step(self, seconds=0.05):
        for index in range(round(seconds / self.model.opt.timestep)):
            if index % 10 == 0:
                check_motion(self)
            old = self.pose[:2]
            mujoco.mj_step(self.model, self.data)
            if any(
                self.data.warning[int(warning)].number
                for warning in (
                    mujoco.mjtWarning.mjWARN_BADQACC,
                    mujoco.mjtWarning.mjWARN_BADQVEL,
                    mujoco.mjtWarning.mjWARN_BADQPOS,
                )
            ):
                self.failed = True
                self.data.ctrl[self.act["wheel"]] = 0
                raise RuntimeError("simulation_numerical_instability")
            self.path_length += float(np.linalg.norm(self.pose[:2] - old))
            for pair in self.contacts():
                if any(
                    n in {"base", "upper_arm", "forearm", "wrist", "palm", "drive_wheel"}
                    or "_segment_" in n
                    or n.startswith("caster_")
                    for n in pair
                ) and any(
                    n.startswith(("source_", "delivery_", "obstacle_", "room_wall_")) for n in pair
                ):
                    self.collisions += 1
        self.trace.append([float(self.data.time), *self.pose.tolist(), *self.block.tolist()])
        self.callback()

    def settle_arm(self, lift, reach, grip, seconds=1.2):
        self.data.ctrl[self.act["wheel"]] = 0
        target = arm_ik(0.14 + reach, 0.33 + lift, self.data.body("base").xpos[2] + 0.22)
        ids = [self.act[n] for n in ("shoulder", "elbow", "wrist")]
        duration = max(seconds, float(np.max(abs(target - self.data.ctrl[ids]))) / 0.7 + 0.6)
        curl = float(np.clip(grip / 0.065, 0, 1)) * 3.6
        for _ in range(round(duration / 0.05)):
            if self.cancelled:
                return False
            self.data.ctrl[ids] += np.clip(target - self.data.ctrl[ids], -0.035, 0.035)
            for side in ("left_curl", "right_curl"):
                index = self.act[side]
                self.data.ctrl[index] += np.clip(curl - self.data.ctrl[index], -0.06, 0.06)
            self.step()
        return True

    def stop(self):
        self.data.ctrl[self.act["wheel"]] = 0
        if self.failed:
            return False
        for _ in range(60):
            self.step(0.05)
            if float(np.linalg.norm(self.data.body("base").cvel)) < 0.02:
                return True
        return False

    def image(self, overview=False):
        if self.renderer is None:
            self.renderer = mujoco.Renderer(self.model, height=480, width=640)
        camera = mujoco.MjvCamera()
        camera.lookat[:] = [0, 0, 0.3]
        camera.distance, camera.azimuth, camera.elevation = 7, 125, -55
        self.renderer.update_scene(self.data, camera=camera if overview else "robot_pov")
        image = self.renderer.render()
        buffer = io.BytesIO()
        Image.fromarray(image).save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()

    def close(self):
        if self.renderer:
            self.renderer.close()


def angle(value):
    return math.atan2(math.sin(value), math.cos(value))
