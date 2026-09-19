import { useState } from 'react';
import type { TelemetryFeed } from '../telemetry/useTelemetry';
import { PACK } from '../telemetry/types';
import { Tag } from '../ui/controls';
import { control, useControl } from './store';

/** Manual checks taken from the build's setup notes. */
const MANUAL: { id: string; text: string; detail: string }[] = [
  { id: 'servo-rail', text: 'Servo rail reads 6.0 V', detail: 'ACEIRMC buck, measured with the multimeter before servos and N20 drivers are connected' },
  { id: 'logic-rail', text: 'ESP32 rail reads 5.0 V', detail: 'LM2596 buck, measured before the ESP32 is connected' },
  { id: 'fuse', text: '15 A main fuse fitted', detail: 'Directly after the battery positive lead; never bypassed' },
  { id: 'casters', text: 'Caster brakes released', detail: 'All four; drive wheels sit 1–2 mm lower than the casters' },
  { id: 'tendons', text: 'Tendon lines seated in guides', detail: 'No fraying where the line changes direction' },
  { id: 'clear', text: 'Area around the robot is clear', detail: 'Arm and tentacle reach included' },
];

function Check(props: { index: number; on: boolean; auto?: boolean; text: string; detail: string; onToggle?: () => void }) {
  return (
    <li className="bg-paper">
      <button
        type="button"
        disabled={props.auto}
        onClick={props.onToggle}
        className="flex w-full items-start gap-4 px-5 py-4 text-left disabled:cursor-default"
      >
        <span className="font-mono text-[10px] tracking-[0.16em] text-blue">{String(props.index).padStart(2, '0')}</span>
        <span
          className={`mt-0.5 grid size-4 shrink-0 place-items-center border ${props.on ? 'border-blue bg-blue' : 'border-ink/35'}`}
          aria-hidden
        >
          {props.on && <span className="size-1.5 bg-white" />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[15px]">
            {props.text}
            {props.auto && <span className="label ml-2 text-[10px] text-ink/45">auto</span>}
          </span>
          <span className="mt-0.5 block text-[13px] text-ink/55">{props.detail}</span>
        </span>
      </button>
    </li>
  );
}

/**
 * Pre-flight gate. Nothing moves until every check passes and the operator arms.
 * Ticks live in memory only, so a reload always starts from an unchecked list.
 */
export function Preflight({ telemetry }: { telemetry: TelemetryFeed }) {
  const { armed } = useControl();
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [armedAt, setArmedAt] = useState<Date | null>(null);

  const volts = telemetry.now?.packVolts;
  // Recorded telemetry must never satisfy a live safety check.
  const batteryOk = telemetry.source !== 'replay' && volts !== undefined && volts >= PACK.nominal;
  const done = MANUAL.filter((item) => ticked.has(item.id)).length + (batteryOk ? 1 : 0);
  const total = MANUAL.length + 1;
  const ready = done === total;

  const toggle = (id: string) =>
    setTicked((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  if (armed) {
    return (
      <div className="hairline flex flex-wrap items-center justify-between gap-3 border bg-paper px-5 py-3">
        <div className="flex items-center gap-3">
          <Tag tone="ok">Armed</Tag>
          <span className="label text-ink/55">
            Pre-flight {total}/{total}
            {armedAt && ` · ${armedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`}
          </span>
          {!batteryOk && <Tag tone="signal">Battery below {PACK.nominal} V</Tag>}
        </div>
        <button
          type="button"
          onClick={() => {
            control.set({ armed: false, stick: { x: 0, y: 0 }, winch: [0, 0, 0], goal: null });
            setTicked(new Set());
          }}
          className="label text-ink/70 hover:text-ink"
        >
          Disarm and reset checks
        </button>
      </div>
    );
  }

  return (
    <div className="hairline border bg-paper">
      <div className="hairline flex flex-wrap items-center justify-between gap-3 border-b px-5 py-3">
        <div className="flex items-center gap-3">
          <Tag tone="ink">Locked</Tag>
          <span className="label text-ink/55">
            Pre-flight {done}/{total}
          </span>
        </div>
        <button
          type="button"
          disabled={!ready}
          onClick={() => {
            setArmedAt(new Date());
            control.set({ armed: true, estop: false });
          }}
          className="label bg-blue px-4 py-2 text-white hover:bg-blue-deep disabled:bg-ink/15 disabled:text-ink/45"
        >
          Arm robot
        </button>
      </div>
      <ol className="grid gap-px bg-ink/15 md:grid-cols-2">
        <Check
          index={1}
          on={batteryOk}
          auto
          text={`Battery at or above ${PACK.nominal} V`}
          detail={
            telemetry.source === 'replay'
              ? 'Paused while a recording is open'
              : volts === undefined
                ? 'Waiting for telemetry'
                : `Reading ${volts.toFixed(2)} V from the pack`
          }
        />
        {MANUAL.map((item, i) => (
          <Check key={item.id} index={i + 2} on={ticked.has(item.id)} text={item.text} detail={item.detail} onToggle={() => toggle(item.id)} />
        ))}
        {(MANUAL.length + 1) % 2 === 1 && <li className="hidden bg-paper md:block" aria-hidden />}
      </ol>
    </div>
  );
}
