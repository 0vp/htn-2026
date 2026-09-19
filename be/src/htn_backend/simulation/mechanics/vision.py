"""Visibility-gated simulator labels; no learned detector or SLAM claims."""

import mujoco
import numpy as np

from ..planning import clear


def visible_objects(world, minimum_pixels=12):
    # Segmentation uses the same occlusion and field of view as the RGB camera.
    renderer = world.renderer
    renderer.enable_segmentation_rendering()
    try:
        renderer.update_scene(world.data, camera="robot_pov")
        segmentation = renderer.render().copy()
    finally:
        renderer.disable_segmentation_rendering()
    result = {}
    for name in (*world.tables, "blue_block"):
        body = world.model.body(name).id
        ids = np.flatnonzero(world.model.geom_bodyid == body)
        mask = np.isin(segmentation[:, :, 0], ids) & (
            segmentation[:, :, 1] == int(mujoco.mjtObj.mjOBJ_GEOM)
        )
        count = int(mask.sum())
        if count < minimum_pixels:
            continue
        ys, xs = np.nonzero(mask)
        result[name] = dict(
            visible_pixels=count,
            image_box=[
                float(xs.min() / 640),
                float(ys.min() / 480),
                float((xs.max() + 1) / 640),
                float((ys.max() + 1) / 480),
            ],
        )
    return result


def exploration_targets(world):
    # Known-map sampling, independent of hidden movable objects. Not SLAM frontiers.
    return {
        f"viewpoint_{index}": np.array([x, y, 0.0])
        for index, (x, y) in enumerate((x, y) for y in (-2.0, 0.0, 2.0) for x in (-2.0, 0.0, 2.0))
        if clear((x, y), world.obstacles)
    }


def camera_metadata(world):
    camera = world.model.camera("robot_pov").id
    to_room = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]])
    transform = np.eye(4)
    transform[:3, :3] = to_room @ world.data.cam_xmat[camera].reshape(3, 3)
    transform[:3, 3] = to_room @ world.data.cam_xpos[camera]
    return dict(
        width=640,
        height=480,
        vertical_fov_degrees=65,
        camera_to_room=transform.tolist(),
        camera_axes="OpenGL: x right, y up, looking along negative z",
    )
