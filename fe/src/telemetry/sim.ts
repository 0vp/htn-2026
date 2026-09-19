import { control, mixDrive } from '../control/store';
import { MAX_RPM, WHEEL_DIAMETER_M, type Telemetry } from './types';

/** Plausible telemetry that reacts to the controls, for use before the robot reports in. */
export function createSim() {
  let restingVolts = 12.45;
  let lastArm = control.get().arm;
  const t: Telemetry = {
    packVolts: restingVolts,
    ampsEstimate: 0.4,
    rpm: { left: 0, right: 0 },
    odometerM: 0,
    servoDeg: { ...lastArm },
    winchPos: [0.3, 0.5, 0.7],
    limits: [
      [false, false],
      [false, false],
      [false, false],
    ],
    rssi: -58,
    loopHz: 200,
    uptimeS: 0,
    heapKb: 212,
  };

  return function step(dt: number): Telemetry {
    const s = control.get();
    const duty = mixDrive(s);
    const lag = 1 - Math.exp(-dt / 0.25);
    const rpmLeft = t.rpm.left + (duty.left * MAX_RPM - t.rpm.left) * lag;
    const rpmRight = t.rpm.right + (duty.right * MAX_RPM - t.rpm.right) * lag;
    const speed = (((rpmLeft + rpmRight) / 2) * Math.PI * WHEEL_DIAMETER_M) / 60;

    const armMoving = (Object.keys(s.arm) as (keyof typeof s.arm)[]).filter((j) => s.arm[j] !== lastArm[j]).length;
    lastArm = s.arm;

    const winchPos = t.winchPos.map((p, i) => {
      const v = s.estop ? 0 : s.winch[i];
      return Math.max(0, Math.min(1, p + v * 0.12 * dt));
    }) as Telemetry['winchPos'];
    const winchActive = s.estop ? 0 : s.winch.filter((w, i) => w !== 0 && winchPos[i] > 0 && winchPos[i] < 1).length;

    const amps =
      0.38 +
      (Math.abs(rpmLeft) + Math.abs(rpmRight)) / MAX_RPM * 2.6 +
      armMoving * 1.4 +
      0.25 * 3 +
      winchActive * 0.45 +
      (Math.random() - 0.5) * 0.08;

    restingVolts = Math.max(9.9, restingVolts - (amps * dt) / 3600 / 5 * 2.7);

    t.rpm = { left: rpmLeft, right: rpmRight };
    t.odometerM += Math.abs(speed) * dt;
    t.ampsEstimate = Math.max(0, amps);
    t.packVolts = restingVolts - amps * 0.035 + (Math.random() - 0.5) * 0.01;
    t.servoDeg = { ...s.arm };
    t.winchPos = winchPos;
    t.limits = winchPos.map((p) => [p <= 0, p >= 1]) as Telemetry['limits'];
    t.rssi = Math.round(-58 + Math.sin(t.uptimeS / 7) * 4 + (Math.random() - 0.5) * 2);
    t.loopHz = Math.round(198 + Math.random() * 4);
    t.uptimeS += dt;
    t.heapKb = Math.round(212 - (t.uptimeS % 60) * 0.05);
    return { ...t, rpm: { ...t.rpm }, winchPos: [...t.winchPos] as Telemetry['winchPos'] };
  };
}
