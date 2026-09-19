# Robot readiness priorities

Each stage requires measured outcomes before expanding capability. Simulation
success does not authorize physical manipulation.

1. **Reliable approach and recovery.** Diagnose all detour delivery failures;
   preserve conservative collision checks; improve path tracking and feasible
   approach selection. Gate: paired open/detour/blocked controller runs, fresh
   seeds, cancellation tests, then a real Astra delivery through the HTTP tools.
2. **Perception-driven execution.** Replace ideal object coordinates and known
   obstacles in a separate evaluation with camera/depth estimates, uncertainty,
   stale-data rejection, occlusion and movement tests. Report this independently
   from oracle-controller results; never silently substitute ground truth.
3. **General manipulation.** Vary dimensions, orientation, support and payload;
   handle lost contact and failed release. Require observable support/contact
   evidence. Real tentacle mechanics still require hardware calibration.
4. **Independent reactive control.** Measured stopping, collision prediction,
   cancellation and communication-loss handling below the reasoning loop. Test
   delayed observations and moving obstacles before claiming dynamic safety.
5. **Physical calibration and integration.** Establish wheel, joint, camera and
   force/encoder contracts. Hardware measurements and physical acceptance cannot
   be completed with the current uncalibrated simulator.
6. **Voice task interaction.** Ground speech in visible scene objects, clarify
   ambiguous targets, support interruption and evidence-based completion. Build
   on the same action/feedback contract; do not bypass controller checks.

Keep one default controller, record failures as well as successes, and keep
recordings and credentials out of git. Public benchmark comparisons require
matching input assumptions and metrics; procedural fixtures are regressions.

## Current gate after inspecting the physical robot

The supplied photos and user confirmation changed the immediate order: finish
supervised single-drive-wheel / separate-steering-wheel calibration first. The
hardware protocol and stopped-by-default firmware now match those actuators;
physical execution and calibration have not been performed. The previous
simulator layout is not the photographed chassis and cannot certify it.

Implemented and tested in this pass: depth-grounding plumbing, improved historical
fixture approach/recovery, motor expiry and footprint guard, honest stop receipts,
physical protocol replacement, serial bridge, firmware compile and native protocol
tests. Still incomplete: calibrated digital twin, perception-driven autonomous
control, dynamic-hazard validation and general/physical manipulation. Voice work
is progressing separately through the existing agent entry point.
