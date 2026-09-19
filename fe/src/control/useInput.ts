import { useEffect, useState } from 'react';
import { JOINT_LIMITS, control, setJoint, setStick, setWinch } from './store';

const DRIVE_KEYS: Record<string, [number, number]> = {
  KeyW: [0, 1],
  ArrowUp: [0, 1],
  KeyS: [0, -1],
  ArrowDown: [0, -1],
  KeyA: [-1, 0],
  ArrowLeft: [-1, 0],
  KeyD: [1, 0],
  ArrowRight: [1, 0],
};

const WINCH_KEYS: Record<string, [0 | 1 | 2, number]> = {
  KeyU: [0, -1],
  KeyJ: [0, 1],
  KeyI: [1, -1],
  KeyK: [1, 1],
  KeyO: [2, -1],
  KeyL: [2, 1],
};

const typing = (target: EventTarget | null) =>
  target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName));

/**
 * Keyboard: WASD / arrows drive, U J · I K · O L winches, Space latches the stop.
 * Gamepad: left stick drives, right stick nudges shoulder and elbow, B/Circle latches the stop.
 * Returns the set of held keys so the pad can light up what is pressed.
 */
export function useInput(): { held: Set<string>; gamepad: string | null } {
  const [held, setHeld] = useState<Set<string>>(new Set());
  const [gamepad, setGamepad] = useState<string | null>(null);

  useEffect(() => {
    const keys = new Set<string>();

    const apply = () => {
      let x = 0;
      let y = 0;
      for (const code of keys) {
        const vector = DRIVE_KEYS[code];
        if (vector) {
          x += vector[0];
          y += vector[1];
        }
      }
      setStick(Math.sign(x), Math.sign(y));
      for (const index of [0, 1, 2] as const) {
        const entries = Object.entries(WINCH_KEYS).filter(([code, [i]]) => i === index && keys.has(code));
        setWinch(index, entries.length === 1 ? entries[0][1][1] : 0);
      }
      setHeld(new Set(keys));
    };

    const down = (event: KeyboardEvent) => {
      if (typing(event.target) || event.metaKey || event.ctrlKey) return;
      if (event.code === 'Space') {
        event.preventDefault();
        if (!event.repeat) control.set((s) => ({ estop: !s.estop }));
        return;
      }
      if (!(event.code in DRIVE_KEYS) && !(event.code in WINCH_KEYS)) return;
      event.preventDefault();
      keys.add(event.code);
      apply();
    };
    const up = (event: KeyboardEvent) => {
      if (keys.delete(event.code)) apply();
    };
    const blur = () => {
      keys.clear();
      apply();
    };

    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    window.addEventListener('blur', blur);
    return () => {
      window.removeEventListener('keydown', down);
      window.removeEventListener('keyup', up);
      window.removeEventListener('blur', blur);
    };
  }, []);

  useEffect(() => {
    let frame = 0;
    let wasPressed = false;
    let wasActive = false;
    const dead = (v: number) => (Math.abs(v) < 0.12 ? 0 : v);

    const poll = () => {
      frame = requestAnimationFrame(poll);
      const pad = navigator.getGamepads?.().find((p) => p?.connected) ?? null;
      setGamepad((current) => (current === (pad?.id ?? null) ? current : (pad?.id ?? null)));
      if (!pad) return;

      const [lx = 0, ly = 0, rx = 0, ry = 0] = pad.axes;
      const x = dead(lx);
      const y = -dead(ly);
      const active = x !== 0 || y !== 0;
      // Only write when the stick is in use so it does not fight the keyboard.
      if (active || wasActive) setStick(x, y);
      wasActive = active;

      const { arm } = control.get();
      if (dead(rx)) setJoint('shoulder', Math.min(JOINT_LIMITS.shoulder[1], arm.shoulder + dead(rx) * 1.5));
      if (dead(ry)) setJoint('elbow', arm.elbow - dead(ry) * 1.5);

      const pressed = pad.buttons[1]?.pressed ?? false;
      if (pressed && !wasPressed) control.set((s) => ({ estop: !s.estop }));
      wasPressed = pressed;
    };
    poll();
    return () => cancelAnimationFrame(frame);
  }, []);

  return { held, gamepad };
}
