import { useEffect, useRef, useState } from 'react';
import { Segmented, Tag } from '../ui/controls';
import { closeSession, openSession, pause, play, seek, setSpeed, usePlayer } from './player';
import { progress, startRecording, stopRecording, useRecorder } from './recorder';

const clock = (ms: number) => {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
};

const megabytes = (bytes: number) => `${(bytes / 1024 / 1024).toFixed(1)} MB`;

/** Record and open buttons for the top bar. */
export function SessionButtons() {
  const { recording, startedAt } = useRecorder();
  const player = usePlayer();
  const input = useRef<HTMLInputElement>(null);
  const [, redraw] = useState(0);

  useEffect(() => {
    if (!recording) return;
    const timer = setInterval(() => redraw((n) => n + 1), 500);
    return () => clearInterval(timer);
  }, [recording]);

  return (
    <div className="label flex items-center">
      <button
        type="button"
        onClick={recording ? stopRecording : startRecording}
        disabled={!!player && !player.error}
        title={recording ? 'Stop and save .htnrec' : 'Record LiDAR, telemetry and commands'}
        className={`flex items-center gap-2 border px-3 py-2 disabled:opacity-40 ${
          recording ? 'border-signal bg-signal text-white' : 'hairline text-ink/75 hover:text-ink'
        }`}
      >
        <span className={`size-2 ${recording ? 'bg-white' : 'rounded-full bg-signal'}`} />
        {recording ? (
          <span className="tabular-nums">
            {clock(Date.now() - startedAt)} · {megabytes(progress.bytes)} · Save
          </span>
        ) : (
          'Rec'
        )}
      </button>
      <button
        type="button"
        onClick={() => input.current?.click()}
        disabled={recording}
        className="hairline border border-l-0 px-3 py-2 text-ink/75 hover:text-ink disabled:opacity-40"
      >
        Open
      </button>
      <input
        ref={input}
        type="file"
        accept=".htnrec"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void openSession(file);
          event.target.value = '';
        }}
      />
    </div>
  );
}

/** Fixed strip shown while a session is open. */
export function ReplayBar() {
  const player = usePlayer();
  if (!player) return null;

  if (player.error) {
    return (
      <div className="label fixed inset-x-0 bottom-0 z-30 flex items-center justify-between gap-4 bg-signal px-6 py-3 text-white sm:px-9">
        <span>
          {player.name} · {player.error}
        </span>
        <button type="button" onClick={closeSession} className="underline">
          Dismiss
        </button>
      </div>
    );
  }

  return (
    <div className="hairline fixed inset-x-0 bottom-0 z-30 flex flex-wrap items-center gap-x-5 gap-y-2 border-t bg-paper/95 px-6 py-3 backdrop-blur sm:px-9">
      <Tag tone="signal">Replay</Tag>
      <span className="label max-w-56 truncate text-ink/70" title={player.name}>
        {player.name}
      </span>
      <span className="font-mono text-[11px] text-ink/50">
        {new Date(player.startedAt).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}
      </span>
      <button
        type="button"
        onClick={player.playing ? pause : play}
        className="label bg-blue px-4 py-1.5 text-white hover:bg-blue-deep"
      >
        {player.playing ? 'Pause' : 'Play'}
      </button>
      <input
        type="range"
        aria-label="Replay position"
        className="slider min-w-40 flex-1"
        min={0}
        max={player.duration}
        step={100}
        value={player.position}
        onChange={(event) => seek(Number(event.target.value))}
      />
      <span className="font-mono text-[12px] tabular-nums">
        {clock(player.position)} / {clock(player.duration)}
      </span>
      <Segmented
        value={String(player.speed)}
        onChange={(v) => setSpeed(Number(v))}
        options={[
          ['1', '1×'],
          ['2', '2×'],
          ['4', '4×'],
        ]}
      />
      <button type="button" onClick={closeSession} className="label text-ink/70 hover:text-ink">
        Back to live
      </button>
    </div>
  );
}
