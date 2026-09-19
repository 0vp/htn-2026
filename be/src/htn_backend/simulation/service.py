"""Isolated simulator HTTP adapter implementing the room-agent contract."""

import copy
import json
import threading
import time
import uuid
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Response

from ..robotics.actions import SkillRequest
from .control.feedback import measure
from .controller import Controller
from .mechanics.vision import camera_metadata, exploration_targets, visible_objects
from .world import World

ROOM = "51A00001"


def room_point(point):
    return [float(point[0]), float(point[2]), -float(point[1])]


class Simulation:
    def __init__(self, seed=0, layout="detour"):
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mujoco")
        self.receipts, self.requests = {}, {}
        self.views = OrderedDict()
        self.frames = deque(maxlen=240)
        self.revision, self.sequence, self.active = 1, 0, None
        self.last_capture = -1.0
        self.snapshot = {}
        self.feedback = {}
        self.feedback_sequence = 0
        self.last_action = None
        self.beliefs, self.evidence = {}, {}
        self.executor.submit(self.initialize, seed, layout).result(timeout=30)

    def initialize(self, seed, layout):
        self.world = World(seed, layout)
        self.controller = Controller(self.world)
        self.waypoints = exploration_targets(self.world)
        self.world.targets = dict(self.waypoints)
        self.world.callback = self.publish
        self.publish(force=True)

    def publish(self, force=False):
        w = self.world
        with self.lock:
            self.feedback_sequence += 1
            self.feedback = measure(w, self.feedback_sequence)
            self.feedback["action_id"] = self.active or self.last_action
            if self.snapshot:
                self.snapshot["robot"]["feedback"] = copy.deepcopy(self.feedback)
        if not force and w.data.time - self.last_capture < 0.75:
            return
        image = w.image()
        self.last_capture = float(w.data.time)
        visible = visible_objects(w)
        for name, pixels in visible.items():
            position = w.block if name == "blue_block" else w.tables[name]
            self.beliefs[name] = dict(
                object_id=name,
                label="blue block" if name == "blue_block" else name.replace("_", " "),
                center=room_point(position),
                last_seen_simulation_s=float(w.data.time),
                evidence_url=f"/v1/rooms/{ROOM}/objects/{name}/evidence.jpg",
                evidence_source="last visible robot POV; full image, not crop",
                source="visibility_gated_simulator_labels_and_poses",
                grasp_ready=False,
                **pixels,
            )
            self.evidence[name] = image
            w.targets[name] = position.copy() if hasattr(position, "copy") else list(position)
        objects = [
            dict(
                obj,
                visibility="visible" if name in visible else "last_seen",
                state="held" if w.held == name else "observed",
                age_simulation_s=float(w.data.time) - obj["last_seen_simulation_s"],
            )
            for name, obj in self.beliefs.items()
        ]
        objects.extend(
            dict(
                object_id=name,
                label=name.replace("_", " "),
                center=room_point(position),
                kind="navigation_waypoint",
                source="known_static_map_sampling",
                visibility="not_an_object",
                grasp_ready=False,
            )
            for name, position in self.waypoints.items()
        )
        with self.lock:
            self.sequence += 1
            observation = dict(
                sequence=self.sequence,
                rgb_available=True,
                received_at=time.time(),
                capture_timestamp_s=float(w.data.time),
                storage_source="simulation",
                view="body-mounted robot POV",
                camera=camera_metadata(w),
                robot_pose=dict(
                    position=room_point(w.data.body("base").xpos), yaw=float(w.pose[2])
                ),
                execution_domain="simulation",
            )
            self.views[self.sequence] = (observation, image)
            self.frames.append(image)
            while len(self.views) > 32:
                self.views.popitem(last=False)
            self.snapshot = dict(
                room_id=ROOM,
                revision=self.revision,
                execution_domain="simulation",
                coordinate_system="right_handed_y_up_meters",
                observation=observation,
                objects=objects,
                robot=dict(
                    pose=observation["robot_pose"],
                    held_object=w.held,
                    feedback=copy.deepcopy(self.feedback),
                ),
                capabilities=dict(
                    observe=True,
                    search=True,
                    inspect=True,
                    navigate=True,
                    pick=True,
                    place=True,
                    pick_includes_local_approach=True,
                    manipulation_scope="simulated rigid block; not arbitrary objects or hardware",
                    stop=True,
                ),
                geometry_contract="Visible simulator labels/poses; known static obstacle map. "
                "No learned perception, pose noise, or SLAM under test. "
                "Last-seen poses can be stale.",
                blockers=[
                    "Narrow approach corridors can block manipulation; see action feedback",
                    "Single steering wheel cannot independently command chassis heading",
                ],
                active_action=self.active,
                metrics=dict(
                    simulation_time_s=float(w.data.time),
                    path_length_m=w.path_length,
                    collision_steps=w.collisions,
                ),
            )

    def scene(self):
        with self.lock:
            return copy.deepcopy(self.snapshot)

    def submit(self, request):
        encoded = request.model_dump_json()
        with self.lock:
            if request.request_id in self.requests:
                ident, previous = self.requests[request.request_id]
                if previous != encoded:
                    raise HTTPException(409, "Request ID reused with different arguments")
                return copy.deepcopy(self.receipts[ident])
            if self.world.failed:
                raise HTTPException(409, "Simulation is invalid; restart before further actions")
            if self.active and request.skill != "stop":
                raise HTTPException(409, "Action running; inspect its receipt or stop it")
            if request.skill != "stop" and request.scene_revision != self.revision:
                raise HTTPException(409, "Scene changed; read_scene before submitting")
            if request.skill != "stop" and request.object_id not in {
                obj["object_id"] for obj in self.snapshot["objects"]
            }:
                raise HTTPException(404, "Unknown simulation target")
            if request.skill == "pick" and request.object_id != "blue_block":
                raise HTTPException(422, "Target is outside the validated simulator grasp scope")
            if request.skill == "place" and request.object_id not in self.world.tables:
                raise HTTPException(422, "Target is not a simulator support surface")
            ident = uuid.uuid4().hex
            receipt = dict(
                action_id=ident,
                request_id=request.request_id,
                room_id=ROOM,
                skill=request.skill,
                object_id=request.object_id,
                scene_revision=self.revision,
                state="running",
                dispatched=True,
                physical_success=False,
                simulation_success=None,
                execution_domain="simulation",
                reasons=[],
                created_at=time.time(),
                result=None,
            )
            self.requests[request.request_id] = (ident, encoded)
            self.receipts[ident] = receipt
            if request.skill == "stop":
                self.world.cancelled = True
            else:
                self.world.cancelled = False
            self.active = ident
            self.world.phase = request.skill
            self.snapshot["active_action"] = ident
            self.executor.submit(self.execute, ident, request)
            return copy.deepcopy(receipt)

    def execute(self, ident, request):
        started = time.monotonic()
        try:
            if request.skill == "inspect":
                success, detail = True, "simulated_scene_evidence"
            else:
                success, detail = self.controller.execute(request.skill, request.object_id)
            cancelled = self.world.cancelled and request.skill != "stop"
            success = bool(success) and not cancelled
            if cancelled:
                detail = "cancelled_by_stop"
            state = "cancelled" if cancelled else ("completed" if success else "failed")
        except Exception as error:
            success, state = False, "failed"
            detail = (
                "simulation_numerical_instability" if self.world.failed else type(error).__name__
            )
        finally:
            self.world.stop()
        self.world.phase = state
        with self.lock:
            receipt = self.receipts[ident]
            receipt.update(
                state=state,
                simulation_success=success,
                reasons=[] if success else [detail],
                result=dict(
                    feedback=detail,
                    held_object=self.world.held,
                    wall_time_s=time.monotonic() - started,
                    collision_steps=self.world.collisions,
                ),
            )
            self.last_action = ident
            if self.active == ident:
                self.active = None
            self.revision += 1
            # Completion and the resulting scene revision become visible together.
            self.publish(force=True)

    def view(self, sequence=None):
        with self.lock:
            sequence = self.sequence if sequence is None else sequence
            if sequence not in self.views:
                raise HTTPException(410, "Simulation observation expired; observe again")
            return self.views[sequence]

    def close(self):
        self.world.cancelled = True
        self.executor.submit(self.world.close).result(timeout=30)
        self.executor.shutdown(wait=True)


def create_app(seed=0, layout="detour"):
    @asynccontextmanager
    async def lifespan(app):
        app.state.sim = Simulation(seed, layout)
        try:
            yield
        finally:
            app.state.sim.close()

    app = FastAPI(title="Robot simulation only", lifespan=lifespan)
    prefix = f"/v1/rooms/{ROOM}"

    @app.get("/health")
    def health():
        return dict(status="ok", execution_domain="simulation", room_id=ROOM)

    @app.get(prefix + "/robot/feedback")
    def feedback():
        with app.state.sim.lock:
            return copy.deepcopy(app.state.sim.feedback)

    @app.get(prefix + "/scene")
    def read_scene():
        return app.state.sim.scene()

    @app.get(prefix + "/scene/search")
    def search(q: str = Query(min_length=1, max_length=256)):
        scene = app.state.sim.scene()
        terms = q.lower().split()
        return dict(
            revision=scene["revision"],
            retrieval_mode="visible_and_last_seen_simulator_labels",
            objects=[o for o in scene["objects"] if all(t in o["label"] for t in terms)],
        )

    @app.get(prefix + "/observations/latest")
    def latest():
        return app.state.sim.view()[0]

    @app.get(prefix + "/observations/history")
    def history(before: int = 2**63 - 1):
        with app.state.sim.lock:
            return dict(
                views=[v[0] for s, v in reversed(app.state.sim.views.items()) if s < before]
            )

    @app.get(prefix + "/observations/{sequence}")
    def observation(sequence: int):
        return app.state.sim.view(sequence)[0]

    @app.get(prefix + "/observations/{sequence}/image.jpg")
    def image(sequence: int):
        return Response(app.state.sim.view(sequence)[1], media_type="image/jpeg")

    @app.get(prefix + "/objects/{object_id}/evidence.jpg")
    def evidence(object_id: str):
        if object_id not in {o["object_id"] for o in app.state.sim.scene()["objects"]}:
            raise HTTPException(404, "Unknown object")
        with app.state.sim.lock:
            image = app.state.sim.evidence.get(object_id)
        if image is None:
            raise HTTPException(404, "No visual evidence for this target")
        return Response(image, media_type="image/jpeg")

    @app.post(prefix + "/observations/ground")
    def ground():
        raise HTTPException(
            409, "RGB-only simulated POV; depth-region grounding is not implemented"
        )

    @app.post(prefix + "/actions")
    def submit(body: SkillRequest):
        return app.state.sim.submit(body)

    @app.get(prefix + "/actions/{action_id}")
    def receipt(action_id: str):
        with app.state.sim.lock:
            if action_id not in app.state.sim.receipts:
                raise HTTPException(404, "Unknown simulation action")
            result = copy.deepcopy(app.state.sim.receipts[action_id])
            result["live_feedback"] = copy.deepcopy(app.state.sim.feedback)
            return result

    @app.get("/snapshot")
    def snapshot():
        return Response(json.dumps(app.state.sim.scene()), media_type="application/json")

    @app.get("/camera.jpg")
    def camera():
        return Response(
            app.state.sim.view()[1], media_type="image/jpeg", headers={"Cache-Control": "no-store"}
        )

    @app.get("/")
    def viewer():
        return Response(
            (Path(__file__).parent / "assets/viewer.html").read_text(), media_type="text/html"
        )

    return app
