import { ControllerPad } from './control/ControllerPad';
import { useCommandLink } from './control/link';
import { control, useControl } from './control/store';
import { LidarView } from './lidar/LidarView';
import { MotionPanel, PowerPanel, SystemPanel } from './panels/Panels';
import { useTelemetry } from './telemetry/useTelemetry';
import { SectionHead, Tag } from './ui/controls';

function Nav({ source }: { source: string }) {
  const { estop } = useControl();
  return (
    <nav className="hairline sticky top-0 z-20 flex items-center justify-between border-b bg-paper/90 px-6 py-3 backdrop-blur sm:px-9">
      <div className="flex items-center gap-8">
        <span className="text-xl tracking-tight">HTN Robot</span>
        <div className="label hidden gap-6 text-ink/75 sm:flex">
          <a href="#lidar" className="hover:text-blue">LiDAR</a>
          <a href="#control" className="hover:text-blue">Control</a>
          <a href="#telemetry" className="hover:text-blue">Telemetry</a>
        </div>
      </div>
      <div className="flex items-center gap-3">
        {source === 'sim' && <Tag tone="ink">Simulated telemetry</Tag>}
        {source === 'waiting' && <Tag tone="blue">Waiting for robot</Tag>}
        <button
          type="button"
          onClick={() => control.set((s) => ({ estop: !s.estop }))}
          className={`label px-4 py-2 ${estop ? 'bg-signal text-white' : 'bg-blue text-white hover:bg-blue-deep'}`}
        >
          {estop ? 'Release stop' : 'Stop all'}
        </button>
      </div>
    </nav>
  );
}

function Bands({ reverse }: { reverse?: boolean }) {
  return (
    <div className={`bands ${reverse ? 'reverse' : ''}`} aria-hidden>
      <div />
      <div />
      <div />
      <div />
    </div>
  );
}

export default function App() {
  const link = useCommandLink();
  const telemetry = useTelemetry();

  return (
    <div className="min-h-screen">
      <Nav source={telemetry.source} />
      <main>
        <LidarView />
        <Bands />

        <div className="paper-dots">
          <section id="control" className="px-6 pt-20 pb-12 sm:px-9">
            <SectionHead
              index="02 — Control"
              title="Drive, arm, tentacle"
              caption="Commands stream to the robot at 20 Hz. The robot should stop on its own if they stop arriving."
            />
            <div className="mt-10">
              <ControllerPad link={link} telemetry={telemetry.now} />
            </div>
          </section>

          <section id="telemetry" className="px-6 pt-12 pb-24 sm:px-9">
            <SectionHead index="03 — Telemetry" title="Health" caption="Last 30 seconds, sampled at 10 Hz." />
            <div className="hairline mt-10 grid gap-px border bg-ink/15 md:grid-cols-2 xl:grid-cols-3">
              <PowerPanel feed={telemetry} />
              <MotionPanel feed={telemetry} />
              <SystemPanel feed={telemetry} link={link} />
            </div>
          </section>
        </div>

        <Bands reverse />
        <footer className="label flex flex-wrap justify-between gap-4 bg-blue px-6 py-6 text-blue-soft sm:px-9">
          <span>Hack the North 2026</span>
          <span>window.lidar.push([[x, y, z], …]) · ?lidar=ws:// · ?control=ws:// · ?telemetry=ws://</span>
        </footer>
      </main>
    </div>
  );
}
