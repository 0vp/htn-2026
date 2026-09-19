# Physical robot reference

The five supplied Downloads photographs are saved as full-resolution JPEGs in
[photos](photos). Image orientation is normalized and metadata is omitted; the
original HEIC files remain in Downloads. Names map directly to IMG_4449–4453.

IMG_4449 is the overhead layout. IMG_4450 shows caster height and the central
wheel from the side. IMG_4451 shows the rail-end servo/small-wheel assembly.
IMG_4452 and IMG_4453 provide opposite and upper views of the drive mount.

The photographs show a central powered wheel and four **swivel wheel casters**,
not ball casters. The user confirmed that the MG90S steers the separate small wheel at one
end of the center rail, while the large powered wheel remains fixed.
The simulator's previous front powered-steering contact and spherical corner
supports therefore are not a calibrated digital twin of this chassis.

No ruler, scale fiducial, encoder record, steering-angle measurement, phone mount
or arm mount is available in these views. Do not infer metric dimensions from
perspective or turn photo proportions into measured steering calibration.
Unknown measurements are explicitly null in [geometry.json](geometry.json).

Before measured autonomous movement, record:

1. Frame footprint and drive/steering contact positions from a marked base origin.
2. Loaded wheel radius and encoder counts across several full wheel rotations.
3. Actual wheel angle for centered and small positive/negative servo commands.
4. Straight-line displacement, yaw change and stopping distance under load.
5. Caster trail/rolling behavior and the fixed phone-to-base transform.

The separate `robot/steering` firmware is the interactive bench controller for
the supplied GPIO wiring. It does not execute the existing automatic startup
sequence. The stopped-by-default firmware has now been uploaded and telemetry verified.
Two low-duty drive pulses returned to reported stop with opposite encoder signs.
The zero-drive steering test lost USB connectivity; the cause is unresolved.
Metric movement and steering calibration remain incomplete.
See [session evidence](../steering/calibration/session.json).

For mistakes learned and the procedure to use on another chassis, see
[base bring-up lessons](base-bringup.md). The latest USB-only results are in
[wired validation](../steering/validation/wired.json).
