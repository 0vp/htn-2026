import type { ReactNode } from 'react';
import type { CommandLink } from '../control/link';
import type { TelemetryFeed } from '../telemetry/useTelemetry';
import { FUSE_AMPS, MAX_RPM, PACK, stateOfCharge } from '../telemetry/types';
import { Meter, Readout, Spark, Tag } from '../ui/controls';

function Panel(props: { index: string; title: string; tag?: ReactNode; children: ReactNode }) {
  return (
    <article className="flex flex-col bg-paper p-6">
      <header className="flex items-center justify-between">
        <p className="label">
          <span className="text-blue">{props.index}</span>
          <span className="ml-3">{props.title}</span>
        </p>
        {props.tag}
      </header>
      <div className="mt-6 flex flex-1 flex-col gap-6">{props.children}</div>
    </article>
  );
}

const avg = (values: number[]) => (values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0);

function duration(seconds: number): string {
  if (!Number.isFinite(seconds)) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m ${String(Math.floor(seconds % 60)).padStart(2, '0')}s`;
}

export function PowerPanel({ feed }: { feed: TelemetryFeed }) {
  const t = feed.now;
  if (!t) return <Panel index="A" title="Power">{null}</Panel>;
  const soc = stateOfCharge(t.packVolts);
  const low = t.packVolts < PACK.nominal - 0.3;
  const amps = avg(feed.history.amps.slice(-50));
  const runtimeS = ((soc * PACK.capacityMah) / 1000 / Math.max(amps, 0.1)) * 3600;
  return (
    <Panel index="A" title="Power · 3S 5000 mAh" tag={low ? <Tag tone="signal">Charge soon</Tag> : undefined}>
      <div className="flex items-end justify-between gap-4">
        <Readout label="Pack" value={t.packVolts.toFixed(2)} unit="V" size="lg" tone={low ? 'fault' : 'normal'} />
        <Readout label="Charge" value={`${Math.round(soc * 100)}`} unit="%" />
        <Readout label="Runtime" value={duration(runtimeS)} />
      </div>
      <Spark values={feed.history.volts} min={PACK.empty} max={PACK.full} limit={PACK.nominal - 0.3} />
      <div>
        <div className="flex items-baseline justify-between">
          <p className="label text-ink/55">Draw vs {FUSE_AMPS} A fuse</p>
          <p className="font-mono text-[12px] tabular-nums">
            {t.ampsEstimate.toFixed(1)} A <span className="text-ink/45">est.</span>
          </p>
        </div>
        <div className="mt-2">
          <Meter value={t.ampsEstimate} max={20} limit={FUSE_AMPS} fault={t.ampsEstimate > FUSE_AMPS * 0.8} />
        </div>
      </div>
    </Panel>
  );
}

export function MotionPanel({ feed }: { feed: TelemetryFeed }) {
  const t = feed.now;
  if (!t) return <Panel index="B" title="Motion">{null}</Panel>;
  const speed = feed.history.speed.at(-1) ?? 0;
  const mismatch = Math.abs(Math.abs(t.rpm.left) - Math.abs(t.rpm.right));
  return (
    <Panel index="B" title="Motion · encoders">
      <div className="flex items-end justify-between gap-4">
        <Readout label="Speed" value={Math.abs(speed).toFixed(2)} unit="m/s" size="lg" />
        <Readout label="Odometer" value={t.odometerM.toFixed(1)} unit="m" />
      </div>
      <Spark values={feed.history.speed.map(Math.abs)} min={0} max={0.22} />
      <div className="grid grid-cols-2 gap-4">
        {(['left', 'right'] as const).map((side) => (
          <div key={side}>
            <div className="flex items-baseline justify-between">
              <p className="label text-ink/55">{side} wheel</p>
              <p className="font-mono text-[12px] tabular-nums">{t.rpm[side].toFixed(1)} rpm</p>
            </div>
            <div className="mt-2">
              <Meter value={Math.abs(t.rpm[side])} max={MAX_RPM} />
            </div>
          </div>
        ))}
      </div>
      <p className="font-mono text-[11px] text-ink/50">
        L/R mismatch {mismatch.toFixed(1)} rpm{mismatch > 4 ? ' · check traction or caster height' : ''}
      </p>
    </Panel>
  );
}

export function SystemPanel({ feed, link }: { feed: TelemetryFeed; link: CommandLink }) {
  const t = feed.now;
  if (!t) return <Panel index="C" title="Controller">{null}</Panel>;
  const weak = t.rssi < -75;
  return (
    <Panel index="C" title="Controller · ESP32-S3">
      <div className="grid grid-cols-2 gap-x-4 gap-y-6">
        <Readout label="Wi-Fi" value={`${t.rssi}`} unit="dBm" tone={weak ? 'warn' : 'normal'} />
        <Readout label="Control loop" value={`${t.loopHz}`} unit="Hz" />
        <Readout label="Uptime" value={duration(t.uptimeS)} />
        <Readout label="Free heap" value={`${t.heapKb}`} unit="KB" />
      </div>
      <dl className="hairline mt-auto grid grid-cols-2 border-t pt-4 font-mono text-[11px]">
        <dt className="text-ink/50">Packets sent</dt>
        <dd className="text-right tabular-nums">{link.sent.toLocaleString()}</dd>
        <dt className="text-ink/50">Command rate</dt>
        <dd className="text-right">20 Hz</dd>
      </dl>
    </Panel>
  );
}
