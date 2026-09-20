import { ControllerPad } from './control/ControllerPad';
import { useCommandLink } from './control/link';
import { Preflight } from './control/Preflight';
import { LidarView } from './lidar/LidarView';
import { MotionPanel, PowerPanel, SystemPanel } from './panels/Panels';
import { usePlayer } from './session/player';
import { ReplayBar } from './session/SessionControls';
import { useTelemetry } from './telemetry/useTelemetry';
import { SectionHead } from './ui/controls';

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
  const player = usePlayer();

  return (
    <div className="min-h-screen">
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
            <div className="mt-10 space-y-6">
              <Preflight telemetry={telemetry} />
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
          <span>Live maps from backend rooms · ?room= · ?control= · ?telemetry= · ?camera=</span>
        </footer>
        {player && <div className="h-16 bg-blue" aria-hidden />}
      </main>
      <ReplayBar />
    </div>
  );
}
