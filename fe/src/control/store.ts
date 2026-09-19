import { useSyncExternalStore } from 'react';

/**
 * Operator intent. Values are normalised so firmware owns the hardware mapping:
 *   drive.left/right  -1..1   signed duty for each BTS7960 (base motors)
 *   arm.*             degrees from each servo's mechanical neutral
 *   winch[i]          -1 reel in, 0 hold, 1 pay out (N20 via TB6612FNG)
 *   goal              world-frame target {x, z} in metres (LiDAR frame), or null
 *   armed             false until the pre-flight checklist passes; nothing moves while false
 */
export type ControlState = {
  estop: boolean;
  stick: { x: number; y: number };
  speedLimit: number;
  arm: { shoulder: number; elbow: number; wrist: number };
  winch: [number, number, number];
  goal: { x: number; z: number } | null;
  armed: boolean;
};

export type Joint = keyof ControlState['arm'];

export const JOINT_LIMITS: Record<Joint, [number, number]> = {
  shoulder: [-90, 90],
  elbow: [-120, 120],
  wrist: [-90, 90],
};

let state: ControlState = {
  estop: false,
  stick: { x: 0, y: 0 },
  speedLimit: 0.5,
  arm: { shoulder: 0, elbow: 0, wrist: 0 },
  winch: [0, 0, 0],
  goal: null,
  armed: false,
};

const listeners = new Set<() => void>();

export const control = {
  get: () => state,
  set(patch: Partial<ControlState> | ((current: ControlState) => Partial<ControlState>)) {
    const next = typeof patch === 'function' ? patch(state) : patch;
    state = { ...state, ...next };
    for (const listener of listeners) listener();
  },
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};

export function useControl(): ControlState {
  return useSyncExternalStore(control.subscribe, control.get);
}

const clamp = (v: number, lo = -1, hi = 1) => Math.max(lo, Math.min(hi, v));

/** True when actuators may move: armed by pre-flight and not stopped. */
export const canMove = (s: ControlState) => s.armed && !s.estop;

/** Arcade mix from stick to differential drive, scaled by the speed limit. */
export function mixDrive(s: ControlState): { left: number; right: number } {
  if (!canMove(s)) return { left: 0, right: 0 };
  const { x, y } = s.stick;
  return {
    left: clamp(y + x) * s.speedLimit,
    right: clamp(y - x) * s.speedLimit,
  };
}

/** Manual stick input overrides and clears any go-to goal. */
export function setStick(x: number, y: number) {
  control.set((s) => ({ stick: { x, y }, goal: x || y ? null : s.goal }));
}

export function setJoint(joint: Joint, degrees: number) {
  const [lo, hi] = JOINT_LIMITS[joint];
  control.set((s) => ({ arm: { ...s.arm, [joint]: clamp(Math.round(degrees), lo, hi) } }));
}

export function setWinch(index: 0 | 1 | 2, value: number) {
  control.set((s) => {
    const winch = [...s.winch] as ControlState['winch'];
    winch[index] = value;
    return { winch };
  });
}

/**
 * The packet sent to the robot. Stop or disarm zeroes every motion request.
 * Firmware drives to `goal` only while the stick is centred; stick input clears the goal.
 */
export function packet(s: ControlState, seq: number) {
  const drive = mixDrive(s);
  return {
    type: 'command',
    seq,
    t: Date.now(),
    estop: s.estop,
    armed: s.armed,
    drive: { left: +drive.left.toFixed(3), right: +drive.right.toFixed(3) },
    arm: s.arm,
    winch: canMove(s) ? s.winch : [0, 0, 0],
    goal: canMove(s) ? s.goal : null,
  };
}
