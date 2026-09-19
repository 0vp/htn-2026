import type { Telemetry } from '../telemetry/types';
import { Segmented, Tag } from '../ui/controls';
import type { CommandLink } from './link';
import { DutyBar, Key, Stick } from './Stick';
import { JOINT_LIMITS, canMove, control, mixDrive, setJoint, setWinch, useControl, type Joint } from './store';
import { useInput } from './useInput';

const JOINTS: { id: Joint; name: string; part: string }[] = [
  { id: 'shoulder', name: 'Shoulder', part: '60 kg servo' },
  { id: 'elbow', name: 'Elbow', part: '25 kg servo' },
  { id: 'wrist', name: 'Wrist', part: '25 kg servo' },
];

const WINCH_KEYS: [string, string][] = [
  ['U', 'J'],
  ['I', 'K'],
  ['O', 'L'],
];

const LINK_TONE = { local: 'ink', connecting: 'blue', open: 'ok', closed: 'signal' } as const;
const LINK_TEXT = { local: 'Local only', connecting: 'Connecting', open: 'Linked', closed: 'Link lost' } as const;

function HoldButton(props: { label: string; active: boolean; disabled: boolean; onHold: (on: boolean) => void }) {
  return (
    <button
      type="button"
      disabled={props.disabled}
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture(event.pointerId);
        props.onHold(true);
      }}
      onPointerUp={() => props.onHold(false)}
      onPointerCancel={() => props.onHold(false)}
      className={`label flex-1 border py-2 text-[10px] touch-none select-none disabled:opacity-40 ${
        props.active ? 'border-blue bg-blue text-white' : 'hairline bg-paper-2 hover:border-ink/40'
      }`}
    >
      {props.label}
    </button>
  );
}

export function ControllerPad(props: { link: CommandLink; telemetry: Telemetry | null }) {
  const s = useControl();
  const { held, gamepad } = useInput();
  const drive = mixDrive(s);
  const on = (...codes: string[]) => codes.some((c) => held.has(c));
  const locked = !canMove(s);

  return (
    <div className="hairline border bg-paper">
      <div className="hairline flex flex-wrap items-center justify-between gap-3 border-b px-5 py-3">
        <div className="flex items-center gap-3">
          <Tag tone={LINK_TONE[props.link.state]}>{LINK_TEXT[props.link.state]}</Tag>
          <span className="label text-ink/55">{gamepad ? `Gamepad · ${gamepad.slice(0, 28)}` : 'Keyboard + pointer'}</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="label text-ink/55">Speed limit</span>
          <Segmented
            value={String(s.speedLimit)}
            onChange={(v) => control.set({ speedLimit: Number(v) })}
            options={[
              ['0.25', '25%'],
              ['0.5', '50%'],
              ['1', '100%'],
            ]}
          />
        </div>
      </div>

      <div className="relative grid gap-px bg-ink/15 lg:grid-cols-[1.1fr_1fr_1fr]">
        {!s.armed && (
          <div className="absolute inset-0 z-10 grid place-items-center bg-paper/70">
            <p className="label bg-ink px-4 py-2 text-paper">Locked · complete pre-flight to arm</p>
          </div>
        )}
        {/* Drive */}
        <div className="bg-paper p-5">
          <p className="label text-ink/55">Drive · BTS7960 ×2</p>
          <div className="mt-4 flex gap-4">
            <div className="max-w-56 flex-1">
              <Stick x={s.stick.x} y={s.stick.y} disabled={locked} />
            </div>
            <DutyBar label="L" value={drive.left} />
            <DutyBar label="R" value={drive.right} />
          </div>
          <div className="mt-4 flex items-center gap-1.5">
            <Key on={on('KeyW', 'ArrowUp')}>W</Key>
            <Key on={on('KeyA', 'ArrowLeft')}>A</Key>
            <Key on={on('KeyS', 'ArrowDown')}>S</Key>
            <Key on={on('KeyD', 'ArrowRight')}>D</Key>
            <span className="label ml-2 text-[10px] text-ink/45">or arrows</span>
          </div>
        </div>

        {/* Arm */}
        <div className="bg-paper p-5">
          <p className="label text-ink/55">Arm · target angle</p>
          <div className="mt-4 space-y-5">
            {JOINTS.map((joint) => {
              const [lo, hi] = JOINT_LIMITS[joint.id];
              return (
                <div key={joint.id}>
                  <div className="flex items-baseline justify-between">
                    <label htmlFor={`joint-${joint.id}`} className="text-[15px]">
                      {joint.name} <span className="font-mono text-[11px] text-ink/45">{joint.part}</span>
                    </label>
                    <span className="font-pixel text-xl tabular-nums">{s.arm[joint.id]}°</span>
                  </div>
                  <input
                    id={`joint-${joint.id}`}
                    type="range"
                    className="slider mt-1"
                    min={lo}
                    max={hi}
                    value={s.arm[joint.id]}
                    disabled={locked}
                    onChange={(event) => setJoint(joint.id, Number(event.target.value))}
                  />
                </div>
              );
            })}
            <button
              type="button"
              className="label text-[10px] text-blue hover:underline"
              onClick={() => control.set({ arm: { shoulder: 0, elbow: 0, wrist: 0 } })}
            >
              Return to neutral
            </button>
          </div>
        </div>

        {/* Tentacle */}
        <div className="bg-paper p-5">
          <p className="label text-ink/55">Tentacle · N20 winches</p>
          <div className="mt-4 space-y-4">
            {([0, 1, 2] as const).map((i) => {
              const pos = props.telemetry?.winchPos[i] ?? 0;
              const [atIn, atOut] = props.telemetry?.limits[i] ?? [false, false];
              return (
                <div key={i}>
                  <div className="flex items-center justify-between">
                    <span className="text-[15px]">Cable {i + 1}</span>
                    <span className="flex items-center gap-2">
                      {atIn && <Tag tone="blue">In stop</Tag>}
                      {atOut && <Tag tone="blue">Out stop</Tag>}
                      <span className="font-mono text-[11px] text-ink/55 tabular-nums">{Math.round(pos * 100)}%</span>
                    </span>
                  </div>
                  <div className="relative mt-2 h-1 bg-ink/10">
                    <div className="absolute inset-y-0 left-0 bg-blue" style={{ width: `${pos * 100}%` }} />
                  </div>
                  <div className="mt-2 flex gap-1.5">
                    <HoldButton
                      label={`In · ${WINCH_KEYS[i][0]}`}
                      active={s.winch[i] === -1}
                      disabled={locked}
                      onHold={(hold) => setWinch(i, hold ? -1 : 0)}
                    />
                    <HoldButton
                      label={`Out · ${WINCH_KEYS[i][1]}`}
                      active={s.winch[i] === 1}
                      disabled={locked}
                      onHold={(hold) => setWinch(i, hold ? 1 : 0)}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="hairline flex flex-wrap items-stretch border-t">
        <button
          type="button"
          onClick={() => control.set((c) => ({ estop: !c.estop }))}
          className={`label flex items-center gap-3 px-6 py-4 text-[12px] ${
            s.estop ? 'bg-signal text-white' : 'bg-ink text-paper hover:bg-signal'
          }`}
        >
          <span className={`size-2 ${s.estop ? 'bg-white' : 'bg-signal'}`} />
          {s.estop ? 'Stopped · release' : 'Stop all'}
          <span className="opacity-60">Space</span>
        </button>
        <code className="flex min-w-0 flex-1 items-center overflow-hidden px-5 py-3 font-mono text-[11px] whitespace-nowrap text-ink/55">
          {props.link.last
            ? `#${props.link.last.seq} drive ${props.link.last.drive.left.toFixed(2)} ${props.link.last.drive.right.toFixed(2)} · arm ${s.arm.shoulder} ${s.arm.elbow} ${s.arm.wrist} · winch ${props.link.last.winch.join(' ')} · 20 Hz`
            : 'Waiting for first packet'}
        </code>
      </div>
    </div>
  );
}
