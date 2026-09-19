import { useRef, type PointerEvent } from 'react';
import { setStick } from './store';

/** Square drag pad for the drive stick. Releasing returns it to centre. */
export function Stick(props: { x: number; y: number; disabled: boolean }) {
  const area = useRef<HTMLDivElement>(null);

  const move = (event: PointerEvent) => {
    const rect = area.current?.getBoundingClientRect();
    if (!rect) return;
    const clamp = (v: number) => Math.max(-1, Math.min(1, v));
    const x = clamp(((event.clientX - rect.left) / rect.width) * 2 - 1);
    const y = clamp(1 - ((event.clientY - rect.top) / rect.height) * 2);
    setStick(+x.toFixed(2), +y.toFixed(2));
  };

  const release = () => setStick(0, 0);

  return (
    <div
      ref={area}
      role="application"
      aria-label="Drive stick. Drag, or use W A S D."
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture(event.pointerId);
        move(event);
      }}
      onPointerMove={(event) => event.buttons && move(event)}
      onPointerUp={release}
      onPointerCancel={release}
      className={`hairline relative aspect-square w-full touch-none border bg-paper-2 select-none ${props.disabled ? 'opacity-40' : 'cursor-crosshair'}`}
    >
      <div className="absolute inset-y-0 left-1/2 w-px bg-ink/15" />
      <div className="absolute inset-x-0 top-1/2 h-px bg-ink/15" />
      <div className="absolute inset-[25%] border border-dashed border-ink/15" />
      <span className="label absolute top-2 left-1/2 -translate-x-1/2 text-[10px] text-ink/40">Fwd</span>
      <span className="label absolute bottom-2 left-1/2 -translate-x-1/2 text-[10px] text-ink/40">Rev</span>
      <div
        className="absolute size-5 -translate-x-1/2 -translate-y-1/2 bg-blue transition-[left,top] duration-75"
        style={{
          left: `calc(14px + (100% - 28px) * ${(props.x + 1) / 2})`,
          top: `calc(14px + (100% - 28px) * ${(1 - props.y) / 2})`,
        }}
      />
    </div>
  );
}

/** Vertical signed bar for one motor's duty, filling up or down from centre. */
export function DutyBar(props: { label: string; value: number }) {
  const pct = Math.abs(props.value) * 50;
  return (
    <div className="flex flex-col items-center gap-2">
      <div className="hairline relative w-5 flex-1 border bg-paper-2">
        <div className="absolute inset-x-0 top-1/2 h-px bg-ink/30" />
        <div
          className="absolute inset-x-0 bg-blue"
          style={props.value >= 0 ? { bottom: '50%', height: `${pct}%` } : { top: '50%', height: `${pct}%` }}
        />
      </div>
      <span className="label text-[10px] text-ink/55">{props.label}</span>
      <span className="font-mono text-[11px] tabular-nums">{Math.round(props.value * 100)}%</span>
    </div>
  );
}

export function Key(props: { children: string; on: boolean }) {
  return (
    <kbd
      className={`inline-flex h-6 min-w-6 items-center justify-center border px-1 font-mono text-[11px] ${
        props.on ? 'border-blue bg-blue text-white' : 'hairline bg-paper-2 text-ink/70'
      }`}
    >
      {props.children}
    </kbd>
  );
}
