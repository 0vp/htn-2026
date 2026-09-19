# Control and evaluation decisions

The useful transfer from Nav2 is geometric planning with tracking clearance,
short-horizon projected-footprint checks, and explicit recovery. Its
[regulated pure pursuit implementation](https://github.com/ros-navigation/navigation2/blob/main/nav2_regulated_pure_pursuit_controller/README.md)
projects motion for collision checks and regulates speed. Our guard follows that
principle using measured planar twist, a bounded command lease, and the actual
oriented chassis/wheel envelope. It is an original small simulator controller,
not Nav2 integration or evidence of equivalent performance.

[Nav2's planner guidance](https://docs.nav2.org/rolling/configuration_and_development/first_time_robot_setup_guide/navigation_plugins/setup_navigation_plugins/)
explains why a circular grid planner can miss feasible motion for non-circular
robots. We retain a conservative global circle and use an oriented local lattice
for escaping manipulation poses. The latter assumes heading stays near its
measured value; its route is checked during execution. It is not a complete
kinodynamic planner. Difficult approach geometry can still fail closed.

[MPPI](https://docs.nav2.org/rolling/configuration_and_development/configuration_guide/controller_plugins/mppi_controller/configuring_mppic/)
is a future candidate after identifying the base dynamics. The historical simulator has one
steering traction contact and four ball casters. The confirmed physical chassis
instead has a fixed powered wheel, separate small steering wheel and four swivel
casters. A bicycle-style model may be appropriate after measuring the contact
geometry, steering linkage and slip; current simulation scores do not validate it.
No independent yaw actuator, pose teleport or grasp weld is introduced.

The existing Astra adapter uses the official
[Codex App Server](https://learn.chatgpt.com/docs/app-server) and active-turn
feedback. Skill execution does not wait for a model response. A model or VLA
cannot replace the motor watchdog, calibration, and observable completion tests.
No new model weights or pi0.5 embodiment policy were installed in this change.

Rendered depth now goes through the same `project_region` function as iPhone
frames. Coordinates are checked against a known wall surface through the HTTP
and agent-tool interfaces. This validates projection and data plumbing, not
learned semantics, object pose estimation, noisy LiDAR performance or SLAM.
Object identities and controller targets still use simulator labels/poses.
