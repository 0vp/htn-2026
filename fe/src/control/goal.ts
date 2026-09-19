import type { Pose } from '../lidar/protocol';

export const ARRIVE_M = 0.12;

const clamp = (v: number, lo = -1, hi = 1) => Math.max(lo, Math.min(hi, v));
const wrap = (a: number) => Math.atan2(Math.sin(a), Math.cos(a));

/**
 * Turn-then-drive steering toward a floor goal, in the same arcade convention as the stick
 * (x > 0 turns clockwise seen from above). Mirrors what firmware should do with `goal`.
 */
export function steerToGoal(pose: Pose, goal: { x: number; z: number }, speedLimit: number) {
  const dx = goal.x - pose.x;
  const dz = goal.z - pose.z;
  const distance = Math.hypot(dx, dz);
  if (distance < ARRIVE_M) return { left: 0, right: 0, distance, arrived: true };
  // Forward is (cos yaw, 0, -sin yaw), so the bearing to the goal is atan2(-dz, dx).
  const error = wrap(Math.atan2(-dz, dx) - pose.yaw);
  const turn = -clamp(error * 1.8);
  const forward = Math.cos(error) > 0.7 ? clamp(distance * 1.5) * Math.cos(error) : 0;
  return {
    left: clamp(forward + turn) * speedLimit,
    right: clamp(forward - turn) * speedLimit,
    distance,
    arrived: false,
  };
}

/** Wheel duty the go-to controller is currently requesting, for the telemetry simulator. */
export const autopilot = { left: 0, right: 0, active: false };
