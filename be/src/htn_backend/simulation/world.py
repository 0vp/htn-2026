"""MuJoCo physics and feedback; no teleports or grasp welds during actions."""

import io
import math

import mujoco
import numpy as np
from PIL import Image

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
        self.data.ctrl[3] = 0.4
        self.step(1)

    @property
    def pose(self):
        return np.array([*self.data.body("base").xpos[:2], self.data.joint("base_yaw").qpos[0]])

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
            frozenset(("blue_block", finger)) in pairs for finger in ("left_finger", "right_finger")
        )

    def step(self, seconds=0.05):
        for _ in range(round(seconds / self.model.opt.timestep)):
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
                self.data.ctrl[:3] = 0
                raise RuntimeError("simulation_numerical_instability")
            self.path_length += float(np.linalg.norm(self.pose[:2] - old))
            for pair in self.contacts():
                if pair & {"base", "lift", "extension", "left_finger", "right_finger"} and any(
                    n.startswith(("source_", "delivery_", "obstacle_")) for n in pair
                ):
                    self.collisions += 1
        self.trace.append([float(self.data.time), *self.pose.tolist(), *self.block.tolist()])
        self.callback()

    def settle_arm(self, lift, reach, grip, seconds=1.2):
        self.data.ctrl[:3] = 0
        target = np.array([lift, reach, grip, grip])
        rate = np.array([0.18, 0.18, 0.10, 0.10])
        duration = max(seconds, float(np.max(abs(target - self.data.ctrl[3:]) / rate)) + 0.6)
        for _ in range(round(duration / 0.05)):
            if self.cancelled:
                return False
            self.data.ctrl[3:] += np.clip(target - self.data.ctrl[3:], -rate * 0.05, rate * 0.05)
            self.step()
        return True

    def stop(self):
        self.data.ctrl[:3] = 0
        if self.failed:
            return False
        self.step(0.5)
        return float(np.linalg.norm(self.data.qvel[self.model.jnt_dofadr[1:4]])) < 0.02

    def image(self):
        if self.renderer is None:
            self.renderer = mujoco.Renderer(self.model, height=480, width=640)
        camera = mujoco.MjvCamera()
        camera.lookat[:] = [0, 0, 0.3]
        camera.distance, camera.azimuth, camera.elevation = 7, 125, -55
        self.renderer.update_scene(self.data, camera=camera)
        image = self.renderer.render()
        buffer = io.BytesIO()
        Image.fromarray(image).save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()

    def close(self):
        if self.renderer:
            self.renderer.close()


def angle(value):
    return math.atan2(math.sin(value), math.cos(value))
