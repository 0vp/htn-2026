"""Assumed hardware dimensions: one driven steering wheel, four ball casters, 3R arm."""


def robot_xml():
    fingers, tendons = [], []
    for side, sign in [("left", -1), ("right", 1)]:
        chain = ""
        for i in reversed(range(5)):
            origin = f"0 {-sign * 0.09} 0" if i == 0 else "0 0 -.035"
            chain = f'''<body name="{side}_segment_{i}" pos="{origin}">
              <joint name="{side}_curl_{i}" axis="{sign} 0 0" range="0 1.3"
                damping=".015" stiffness=".04" armature=".0001"/>
              <geom name="{side}_segment_{i}" type="capsule" fromto="0 0 0 0 0 -.035"
                size=".010" mass=".012" friction="2 .02 .005" condim="6"
                rgba=".9 .55 .18 1"/>{chain}</body>'''
        fingers.append(chain)
        joints = "".join(f'<joint joint="{side}_curl_{i}" coef="1"/>' for i in range(5))
        tendons.append(f'<fixed name="{side}_curl">{joints}</fixed>')
    body = f"""<body name="base" pos="-1.5 -1.5 .18">
      <freejoint name="base_free"/>
      <geom name="base" type="box" size=".23 .22 .09" mass="20" rgba=".12 .18 .25 1"/>
      <body name="steering" pos=".34 0 -.085">
        <joint name="steering" axis="0 0 1" range="-1.57 1.57" damping="1"/>
        <geom type="box" size=".025 .025 .035" mass=".2" contype="0" conaffinity="0"/>
        <body name="drive_wheel">
          <joint name="wheel" axis="0 1 0" damping=".02"/>
          <geom name="drive_wheel" type="cylinder" size=".095 .026" euler="1.570796 0 0"
            mass=".4" friction="1 .002 .0001" rgba=".07 .07 .07 1"/>
        </body>
      </body>
      <body name="caster_fl" pos="0.18 0.18 -.14">
        <joint name="caster_fl" type="ball" damping=".0005" armature=".00001"/>
        <geom name="caster_fl" type="sphere" size=".04" mass=".1"
          friction="1 .001 .0001" condim="6"/>
      </body>
      <body name="caster_fr" pos="0.18 -0.18 -.14">
        <joint name="caster_fr" type="ball" damping=".0005" armature=".00001"/>
        <geom name="caster_fr" type="sphere" size=".04" mass=".1"
          friction="1 .001 .0001" condim="6"/>
      </body>
      <body name="caster_rl" pos="-0.18 0.18 -.14">
        <joint name="caster_rl" type="ball" damping=".0005" armature=".00001"/>
        <geom name="caster_rl" type="sphere" size=".04" mass=".1"
          friction="1 .001 .0001" condim="6"/>
      </body>
      <body name="caster_rr" pos="-0.18 -0.18 -.14">
        <joint name="caster_rr" type="ball" damping=".0005" armature=".00001"/>
        <geom name="caster_rr" type="sphere" size=".04" mass=".1"
          friction="1 .001 .0001" condim="6"/>
      </body>
      <geom type="capsule" fromto="-.23 .2 .1 -.23 .2 1.02" size=".018" mass=".2"/>
      <camera name="robot_pov" pos=".22 0 1.02" xyaxes="0 -1 0 .208 0 .978" fovy="65"/>
      <body name="shoulder" pos="0 0 .22">
        <joint name="shoulder" axis="0 1 0" range="-2.5 1.5" damping="4"/>
        <geom name="upper_arm" type="capsule" fromto="0 0 0 .4 0 0" size=".025" mass=".5"/>
        <body name="elbow" pos=".4 0 0">
          <joint name="elbow" axis="0 1 0" range="-2.6 2.6" damping="3"/>
          <geom name="forearm" type="capsule" fromto="0 0 0 .35 0 0" size=".022" mass=".35"/>
          <body name="wrist" pos=".35 0 0">
            <joint name="wrist" axis="0 1 0" range="-2.6 2.6" damping="2"/>
            <geom name="wrist" type="capsule" fromto="0 0 0 .1 0 0" size=".02" mass=".15"/>
            <body name="palm" pos=".1 0 0">
              <geom name="palm" type="box" size=".025 .10 .015" mass=".1"/>
              <site name="grasp" pos="0 0 -.1" size=".008"/>
              {"".join(fingers)}
            </body>
          </body>
        </body>
      </body>
    </body>"""
    actuators = """<position name="steering" joint="steering" kp="35" kv="4" forcerange="-8 8"/>
      <velocity name="wheel" joint="wheel" kv="4" forcerange="-5 5"/>
      <position name="shoulder" joint="shoulder" kp="180" kv="20" forcerange="-30 30"/>
      <position name="elbow" joint="elbow" kp="140" kv="15" forcerange="-20 20"/>
      <position name="wrist" joint="wrist" kp="80" kv="8" forcerange="-10 10"/>
      <position name="left_curl" tendon="left_curl" kp=".4" kv=".03" forcerange="-.6 .6"/>
      <position name="right_curl" tendon="right_curl" kp=".4" kv=".03" forcerange="-.6 .6"/>"""
    return body, actuators, "".join(tendons)
