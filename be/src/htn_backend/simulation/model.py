"""Procedural MuJoCo mobile manipulator; geometry is an explicit test fixture."""

import numpy as np


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
        {"".join(bodies)}
        <body name="blue_block" pos="{" ".join(map(str, block))}">
          <freejoint/><geom name="blue_block" type="box" size=".035 .035 .035"
            mass=".08" rgba=".1 .3 .9 1" friction="2 .02 .002"/>
        </body>
        <body name="base" pos="-1.5 -1.5 .18">
          <joint name="base_x" type="slide" axis="1 0 0" damping="8"/>
          <joint name="base_y" type="slide" axis="0 1 0" damping="8"/>
          <joint name="base_yaw" axis="0 0 1" damping="8"/>
          <geom name="base" type="cylinder" size=".24 .14" mass="20" rgba=".12 .18 .25 1"/>
          <geom type="cylinder" pos="0 .24 -.09" size=".095 .025"
            euler="1.5708 0 0" contype="0" conaffinity="0" rgba=".05 .05 .05 1"/>
          <geom type="cylinder" pos="0 -.24 -.09" size=".095 .025"
            euler="1.5708 0 0" contype="0" conaffinity="0" rgba=".05 .05 .05 1"/>
          <geom type="box" pos="-.08 0 .35" size=".045 .045 .35" mass="2"/>
          <body name="lift" pos="0 0 .22">
            <joint name="lift" type="slide" axis="0 0 1" range="0 .65"/>
            <geom type="box" size=".07 .07 .04" mass="1" rgba=".95 .65 .1 1"/>
            <body name="extension" pos=".14 0 0">
              <joint name="reach" type="slide" axis="1 0 0" range="0 .6"/>
              <geom type="box" pos="-.08 0 0" size=".1 .035 .025" mass=".5"/>
              <site name="grasp" pos="0 0 -.07" size=".008"/>
              <body name="left_finger" pos="0 .085 -.07">
                <joint name="left" type="slide" axis="0 -1 0" range="0 .075" damping="1"/>
                <geom name="left_finger" type="box" size=".045 .012 .035"
                  mass=".1" friction="3 .05 .02" condim="6" solref=".005 1" rgba=".9 .65 .1 1"/>
              </body>
              <body name="right_finger" pos="0 -.085 -.07">
                <joint name="right" type="slide" axis="0 1 0" range="0 .075" damping="1"/>
                <geom name="right_finger" type="box" size=".045 .012 .035"
                  mass=".1" friction="3 .05 .02" condim="6" solref=".005 1" rgba=".9 .65 .1 1"/>
              </body>
            </body>
          </body>
        </body>
      </worldbody>
      <actuator>
        <velocity name="base_x" joint="base_x" kv="400"/>
        <velocity name="base_y" joint="base_y" kv="400"/>
        <velocity name="base_yaw" joint="base_yaw" kv="150"/>
        <position name="lift" joint="lift" kp="1200" kv="90"/>
        <position name="reach" joint="reach" kp="600" kv="50"/>
        <position name="left" joint="left" kp="400" kv="8" forcerange="-15 15"/>
        <position name="right" joint="right" kp="400" kv="8" forcerange="-15 15"/>
      </actuator>
    </mujoco>'''
    return xml, tables, obstacles
