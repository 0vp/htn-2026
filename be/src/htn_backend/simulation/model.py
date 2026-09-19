"""Procedural MuJoCo mobile manipulator; geometry is an explicit test fixture."""

import numpy as np

from .mechanics.robot import robot_xml


def scene(seed=0, layout="detour"):
    rng = np.random.default_rng(seed)
    offset = rng.uniform(-0.12, 0.12, 2)
    tables = {
        "source_table": [1.4 + offset[0], 0.5 + offset[1], 0.65],
        "delivery_table": [-1.35, 1.3, 0.65],
    }
    obstacles = [(x, y, 0.45, 0.5) for x, y, _ in tables.values()]
    if layout == "detour":
        obstacles.append((0, -0.35, 0.38, 0.48))
    elif layout == "blocked":
        obstacles.append((0, 0, 0.12, 3))
    elif layout != "open":
        raise ValueError("Unknown benchmark layout")
    x, y, z = tables["source_table"]
    block = [x - 0.28, y, z + 0.036]
    bodies = []
    for name, (tx, ty, tz) in tables.items():
        bodies.append(f'''<body name="{name}" pos="{tx} {ty} {tz - 0.04}">
          <geom name="{name}" type="box" size=".45 .5 .04" rgba=".55 .32 .15 1"/>
          <geom type="box" pos="-.35 -.4 -.29" size=".04 .04 .29"/>
          <geom type="box" pos=".35 .4 -.29" size=".04 .04 .29"/>
          <geom type="box" pos="-.35 .4 -.29" size=".04 .04 .29"/>
          <geom type="box" pos=".35 -.4 -.29" size=".04 .04 .29"/>
        </body>''')
    for index, (ox, oy, sx, sy) in enumerate(obstacles[2:]):
        bodies.append(
            f'<geom name="obstacle_{index}" type="box" pos="{ox} {oy} .5" '
            f'size="{sx} {sy} .5" rgba=".5 .55 .6 1"/>'
        )
    robot, actuators, tendons = robot_xml()
    xml = f'''<mujoco model="room_robot_benchmark">
      <compiler angle="radian"/>
      <option timestep=".002" integrator="implicitfast" cone="elliptic"
        impratio="10" noslip_iterations="10"/>
      <default><geom friction="1.2 .02 .002" condim="4"/>
        <joint damping="15" armature=".02"/></default>
      <visual><global offwidth="640" offheight="480"/></visual>
      <worldbody>
        <light pos="0 0 5" dir="0 0 -1" diffuse=".9 .9 .9"/>
        <geom name="floor" type="plane" size="3 3 .1" rgba=".85 .86 .88 1"/>
        <geom name="room_wall_e" type="box" pos="3.2 0 1.3" size=".1 3.3 1.3"
          rgba=".73 .77 .8 1"/>
        <geom name="room_wall_w" type="box" pos="-3.2 0 1.3" size=".1 3.3 1.3"
          rgba=".8 .78 .73 1"/>
        <geom name="room_wall_n" type="box" pos="0 3.2 1.3" size="3.3 .1 1.3"
          rgba=".8 .78 .73 1"/>
        <geom name="room_wall_s" type="box" pos="0 -3.2 1.3" size="3.3 .1 1.3"
          rgba=".73 .77 .8 1"/>
        {"".join(bodies)}
        <body name="blue_block" pos="{" ".join(map(str, block))}">
          <freejoint/><geom name="blue_block" type="box" size=".035 .035 .035"
            mass=".08" rgba=".1 .3 .9 1" friction="2 .02 .002"/>
        </body>
        {robot}
      </worldbody>
      <tendon>{tendons}</tendon>
      <actuator>{actuators}</actuator>
    </mujoco>'''
    return xml, tables, obstacles
