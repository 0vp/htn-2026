/**
 * Robot telemetry. A live source sends this object as JSON (any subset of fields is merged).
 * Each field notes the hardware that produces it on the current build.
 */
export type Telemetry = {
  /** Pack voltage via a resistor divider on an ESP32 ADC pin. 3S: 12.6 full, 9.9 empty. */
  packVolts: number;
  /** Estimated from commanded duty; the build has no current sensor yet. */
  ampsEstimate: number;
  /** Walfront encoder speeds in wheel RPM (40 RPM gearbox). */
  rpm: { left: number; right: number };
  /** Encoder-integrated distance, metres. */
  odometerM: number;
  /** Commanded angles; hobby servos report no position back. */
  servoDeg: { shoulder: number; elbow: number; wrist: number };
  /** Winch spool position 0 (fully in) to 1 (fully out), time-integrated between end stops. */
  winchPos: [number, number, number];
  /** DAOKI end stops per winch: [in, out]. */
  limits: [[boolean, boolean], [boolean, boolean], [boolean, boolean]];
  /** ESP32-S3 health. */
  rssi: number;
  loopHz: number;
  uptimeS: number;
  heapKb: number;
};

export const PACK = { full: 12.6, nominal: 11.1, empty: 9.9, capacityMah: 5000 } as const;
export const FUSE_AMPS = 15;
export const WHEEL_DIAMETER_M = 0.095;
export const MAX_RPM = 40;

/** Rough resting-voltage to state-of-charge curve for a 3S LiPo. */
export function stateOfCharge(volts: number): number {
  const perCell = volts / 3;
  const curve: [number, number][] = [
    [3.3, 0],
    [3.6, 0.1],
    [3.7, 0.3],
    [3.75, 0.45],
    [3.8, 0.55],
    [3.85, 0.65],
    [3.95, 0.8],
    [4.1, 0.95],
    [4.2, 1],
  ];
  if (perCell <= curve[0][0]) return 0;
  for (let i = 1; i < curve.length; i++) {
    const [v1, s1] = curve[i];
    const [v0, s0] = curve[i - 1];
    if (perCell <= v1) return s0 + ((perCell - v0) / (v1 - v0)) * (s1 - s0);
  }
  return 1;
}
