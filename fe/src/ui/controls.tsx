import type { ReactNode } from 'react';

type Tone = 'light' | 'dark';

const frame = (tone: Tone) => (tone === 'dark' ? 'hairline-light' : 'hairline');

export function Segmented<T extends string>(props: {
  value: T;
  onChange: (value: T) => void;
  options: [T, string][];
  tone?: Tone;
}) {
  const tone = props.tone ?? 'light';
  return (
    <div className={`label inline-flex border ${frame(tone)}`} role="radiogroup">
      {props.options.map(([value, text]) => {
        const on = value === props.value;
        const onStyle = tone === 'dark' ? 'bg-paper text-blue' : 'bg-blue text-white';
        const offStyle = tone === 'dark' ? 'text-white/80 hover:text-white' : 'text-ink/60 hover:text-ink';
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => props.onChange(value)}
            className={`px-3 py-1.5 ${on ? onStyle : offStyle}`}
          >
            {text}
          </button>
        );
      })}
    </div>
  );
}

export function TextButton(props: {
  children: ReactNode;
  onClick: () => void;
  tone?: Tone;
  active?: boolean;
}) {
  const tone = props.tone ?? 'light';
  const idle = tone === 'dark' ? 'text-white/80 hover:text-white' : 'text-ink/70 hover:text-ink';
  const on = tone === 'dark' ? 'bg-paper text-blue' : 'bg-ink text-paper';
  return (
    <button
      type="button"
      onClick={props.onClick}
      className={`label border px-3 py-1.5 ${frame(tone)} ${props.active ? on : idle}`}
    >
      {props.children}
    </button>
  );
}

/** Numbered section heading in the reference's style: blue index, pixel title, mono caption. */
export function SectionHead(props: { index: string; title: string; caption?: string; right?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <p className="label text-blue">{props.index}</p>
        <h2 className="mt-2 font-pixel text-4xl leading-none sm:text-5xl">{props.title}</h2>
        {props.caption && <p className="mt-3 max-w-md text-[15px] text-ink/65">{props.caption}</p>}
      </div>
      {props.right}
    </header>
  );
}

/** A labelled value. `unit` is set smaller so the number reads first. */
export function Readout(props: {
  label: string;
  value: string;
  unit?: string;
  tone?: 'normal' | 'warn' | 'fault';
  size?: 'md' | 'lg';
}) {
  const color = props.tone === 'fault' ? 'text-signal' : props.tone === 'warn' ? 'text-[#b25e00]' : '';
  return (
    <div>
      <p className="label text-ink/55">{props.label}</p>
      <p className={`mt-1.5 font-pixel leading-none tabular-nums ${props.size === 'lg' ? 'text-5xl' : 'text-3xl'} ${color}`}>
        {props.value}
        {props.unit && <span className="ml-1 font-mono text-xs tracking-normal text-ink/50">{props.unit}</span>}
      </p>
    </div>
  );
}

/** Horizontal meter with optional limit tick; value and limit share the same scale. */
export function Meter(props: { value: number; max: number; limit?: number; fault?: boolean }) {
  const pct = Math.max(0, Math.min(1, props.value / props.max)) * 100;
  return (
    <div className="relative h-2 w-full bg-ink/8">
      <div className={`h-full ${props.fault ? 'bg-signal' : 'bg-blue'}`} style={{ width: `${pct}%` }} />
      {props.limit !== undefined && (
        <div
          className="absolute -top-1 h-4 w-px bg-ink"
          style={{ left: `${(props.limit / props.max) * 100}%` }}
          aria-hidden
        />
      )}
    </div>
  );
}

/** Minimal line chart for a rolling series. Axis-free on purpose; the readout carries the number. */
export function Spark(props: { values: number[]; min: number; max: number; height?: number; limit?: number }) {
  const height = props.height ?? 48;
  const width = 240;
  const span = props.max - props.min || 1;
  const y = (v: number) => height - ((Math.max(props.min, Math.min(props.max, v)) - props.min) / span) * height;
  const step = props.values.length > 1 ? width / (props.values.length - 1) : width;
  const d = props.values.map((v, i) => `${i ? 'L' : 'M'}${(i * step).toFixed(1)},${y(v).toFixed(1)}`).join('');
  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="block w-full" style={{ height }}>
      {props.limit !== undefined && (
        <line x1={0} x2={width} y1={y(props.limit)} y2={y(props.limit)} stroke="#eb1700" strokeDasharray="3 3" strokeWidth={1} vectorEffect="non-scaling-stroke" />
      )}
      <path d={d} fill="none" stroke="#1520b8" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function Tag(props: { children: ReactNode; tone?: 'blue' | 'ink' | 'signal' | 'ok' }) {
  const styles = {
    blue: 'border-blue text-blue',
    ink: 'border-ink/40 text-ink/70',
    signal: 'border-signal bg-signal text-white',
    ok: 'border-ok text-ok',
  };
  return <span className={`label border px-1.5 py-0.5 text-[10px] ${styles[props.tone ?? 'ink']}`}>{props.children}</span>;
}
