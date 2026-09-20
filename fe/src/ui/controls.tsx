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
