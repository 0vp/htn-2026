"""Contact-verified manipulation of the fixture's rigid object, with measured hand control."""

import numpy as np

from .approach import approach, footprint_clear, relative_target
from .arm import move_hand


def pick(controller, object_id):
    w = controller.world
    if object_id != "blue_block":
        return False, "object_not_graspable"
    if w.held:
        return False, "gripper_occupied"
    target = np.array(getattr(w, "targets", {}).get(object_id, w.block)).copy()
    local = relative_target(w, target)
    if np.linalg.norm(local) > 1.2:
        return False, "target_outside_local_approach: navigate to object first"
    if not (0.6 < local[0] < 0.68 and abs(local[1]) < 0.015):
        success, detail = approach(controller, target)
        if not success:
            return False, detail
        local = relative_target(w, target)
    if not footprint_clear(w.pose, w.obstacles):
        return False, "base_approach_clearance_lost"
    latest = np.array(getattr(w, "targets", {}).get(object_id, target))
    if np.linalg.norm(latest - target) > 0.02:
        return False, "target_moved_during_approach"
    original = w.block.copy()
    half_height = float(w.model.geom(object_id).size[2])
    grasp_height = target[2] - half_height + 0.175 - 0.1 + 0.02
    for phase, reach, height, curl in (
        ("pregrasp", local[0], grasp_height + 0.05, 0),
        ("grasp_descent", local[0], grasp_height, 0),
        ("tentacle_closure", local[0], grasp_height, 1),
    ):
        w.phase = phase
        success, detail = move_hand(w, reach, height, curl)
        if not success:
            return False, detail
    if not w.grasp_contacts():
        move_hand(w, local[0], grasp_height + 0.05, 0)
        return False, "bilateral_tentacle_contact_not_found"
    w.held = object_id
    w.phase = "lift_verification"
    success, detail = move_hand(w, 0.5, target[2] + 0.22, 1)
    w.step(0.5)
    lifted = w.block[2] - original[2] > 0.1 and w.grasp_contacts()
    w.control_feedback.update(
        lift_m=float(w.block[2] - original[2]), bilateral_contact=w.grasp_contacts()
    )
    if not w.grasp_contacts():
        w.held = None
    return (
        bool(success and lifted),
        "lift_and_retained_contact_verified"
        if success and lifted
        else detail
        if not success
        else "grasp_lost_or_insufficient_lift",
    )


def support_targets(w, table):
    center = np.array(table[:2])
    candidates = []
    for forward, extent in (
        (np.array([1.0, 0]), 0.45),
        (np.array([-1.0, 0]), 0.45),
        (np.array([0.0, 1]), 0.5),
        (np.array([0.0, -1]), 0.5),
    ):
        point = center - forward * (extent - 0.12)
        candidates.append(np.array([*point, table[2]]))
    return sorted(candidates, key=lambda p: float(np.linalg.norm(p[:2] - w.pose[:2])))


def place(controller, object_id):
    w = controller.world
    if not w.held:
        return False, "gripper_empty"
    table = w.tables.get(object_id)
    if table is None:
        return False, "target_is_not_a_support_surface"
    for point in support_targets(w, table):
        success, detail = approach(controller, point)
        if success:
            break
        if w.cancelled or w.collisions:
            return False, detail
    else:
        return False, "support_approach_unreachable"
    local = relative_target(w, point)
    # Open tentacle tips remain 2 cm above the surface. The rigid fixture block
    # settles under gravity; this is not a force-controlled fragile-object placement.
    release_height = table[2] + 0.175 - 0.1 + 0.02
    for phase, reach, height, curl in (
        ("place_approach", local[0], release_height + 0.05, 1),
        ("place_descent", local[0], release_height, 1),
        ("release", local[0], release_height, 0),
        ("release_retreat", 0.4, release_height + 0.15, 0),
    ):
        w.phase = phase
        success, detail = move_hand(w, reach, height, curl)
        if not success:
            return False, detail
    w.step(1)
    supported = (
        abs(w.block[0] - table[0]) < 0.42
        and abs(w.block[1] - table[1]) < 0.47
        and abs(w.block[2] - table[2] - 0.035) < 0.015
        and frozenset(("blue_block", object_id)) in w.contacts()
        and np.linalg.norm(w.data.body("blue_block").cvel) < 0.04
        and not w.grasp_contacts()
    )
    if not w.grasp_contacts():
        w.held = None
    return bool(
        supported
    ), "released_object_support_and_rest_verified" if supported else "release_not_stably_supported"
