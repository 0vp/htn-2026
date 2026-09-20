"""Open-loop wheel calibration on the floor, measured with the laptop camera (see sense.py).

  python calibrate.py /dev/cu.usbserial-10            # needs ~0.5 m clear in front and behind

Every test pulse is followed by its reverse so the robot stays roughly in place.
Writes calibration.json, which base.py applies for teleop.py and agent_bridge.py.
Ctrl-C stops the motors. Keep a hand near the battery disconnect.
"""

import argparse
import json
import time

from base import CALIBRATION, DEFAULTS, Base
from sense import VisualGyro, settle

YAW_MOVED_DEG = 1.5


def pulse(base, gyro, left, right, seconds, undo=True):
    """Raw-duty pulse; returns (yaw change in degrees, log scale change)."""
    yaw0, scale0 = settle(gyro)
    base.run(left, right, seconds)
    yaw1, scale1 = settle(gyro, 1.0)
    if undo:
        base.run(-left, -right, seconds)
    return yaw1 - yaw0, scale1 - scale0


def raw(base, left, right):
    """Base maps 0..1 onto min..max duty; with default calibration that is value * max_duty."""
    return left / base.max_duty, right / base.max_duty


def find_minimum(base, gyro, side, top, seconds):
    duty = 0.08
    while duty <= top:
        pair = (duty, 0) if side == "left" else (0, duty)
        yaw, _ = pulse(base, gyro, *raw(base, *pair), seconds)
        print(f"  {side} duty {duty:.2f}: yaw {yaw:+.2f} deg", flush=True)
        if abs(yaw) >= YAW_MOVED_DEG:
            # Left wheel forward turns the robot right (negative yaw); right wheel the opposite.
            forward = -1 if yaw > 0 else 1
            return duty, forward if side == "left" else -forward
        duty += 0.03
    raise SystemExit(f"{side} wheel never moved the robot up to duty {top}; check power/wiring")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port")
    parser.add_argument("--camera-faces", choices=("rear", "front"), default="rear")
    parser.add_argument(
        "--signs", help="Known forward polarity 'L,R' (e.g. 1,1 from a lifted-wheel check)"
    )
    parser.add_argument("--mins", help="Skip step 1 and use these minimum moving duties 'L,R'")
    parser.add_argument("--top", type=float, default=0.45, help="Highest raw duty to try")
    parser.add_argument("--level", type=float, default=0.35, help="0..1 level for trim/spin runs")
    parser.add_argument("--seconds", type=float, default=0.8)
    args = parser.parse_args()
    gyro = VisualGyro()
    cal = dict(DEFAULTS)
    try:
        with Base(args.port, raw=True) as base:
            print("1/3 minimum moving duty and direction per wheel")
            for side in () if args.mins else ("left", "right"):
                cal[f"{side}_min"], cal[f"{side}_sign"] = find_minimum(
                    base, gyro, side, args.top, args.seconds
                )
            if args.mins:
                cal["left_min"], cal["right_min"] = (float(v) + 0.03 for v in args.mins.split(","))
            if args.signs:
                cal["left_sign"], cal["right_sign"] = (int(v) for v in args.signs.split(","))
            # Margin under the measured minimum so level 0+ starts just below motion.
            for side in ("left", "right"):
                cal[f"{side}_min"] = round(max(cal[f"{side}_min"] - 0.03, 0.0), 3)
            base.cal = cal

            print("2/3 forward direction check and straight-line trim")
            _, scale = pulse(base, gyro, args.level, args.level, args.seconds)
            toward_camera = scale > 0
            if toward_camera == (args.camera_faces == "rear"):
                # Drove the wrong way: both yaw-derived signs were from swapped sides.
                cal["left_sign"], cal["right_sign"] = -cal["left_sign"], -cal["right_sign"]
                cal["swap"] = True
                print("  sides are swapped relative to the wiring labels; corrected in software")
            history = []
            for _ in range(6):
                forward, _ = pulse(base, gyro, args.level, args.level, args.seconds, undo=False)
                backward, _ = pulse(base, gyro, -args.level, -args.level, args.seconds, undo=False)
                drift = (forward - backward) / 2  # + means the right wheel outruns the left.
                history.append(round(drift, 2))
                print(f"  drift {drift:+.2f} deg  gains L{cal['left_gain']:.3f} R{cal['right_gain']:.3f}")
                if abs(drift) < 0.7:
                    break
                left_key, right_key = (
                    ("right_gain", "left_gain") if cal["swap"] else ("left_gain", "right_gain")
                )
                ratio = cal[right_key] / cal[left_key] * (1 - 0.025 * max(-8, min(8, drift)))
                ratio = max(0.5, min(2.0, ratio))
                slow, fast = (round(1 / ratio, 3), 1.0) if ratio > 1 else (1.0, round(ratio, 3))
                # Gains are stored per driver; with swap the logical left is the "right" driver.
                keys = ("right_gain", "left_gain") if cal["swap"] else ("left_gain", "right_gain")
                cal[keys[0]], cal[keys[1]] = slow, fast

            print("3/3 spin rate")
            ccw, _ = pulse(base, gyro, -args.level, args.level, args.seconds, undo=False)
            cw, _ = pulse(base, gyro, args.level, -args.level, args.seconds, undo=False)
            cal["measured"] = dict(
                date=time.strftime("%Y-%m-%d %H:%M"),
                level=args.level,
                pulse_s=args.seconds,
                drift_history_deg=history,
                spin_ccw_deg_per_s=round(ccw / args.seconds, 1),
                spin_cw_deg_per_s=round(cw / args.seconds, 1),
                note="Yaw from camera with assumed 54 deg HFOV; includes ramp time. No metric speed.",
            )
    finally:
        gyro.close()
    CALIBRATION.write_text(json.dumps(cal, indent=2) + "\n")
    print(json.dumps(cal, indent=2))


if __name__ == "__main__":
    main()
