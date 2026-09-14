# M8-C Real-SIESTA Full-SOC Fixture Preparation

These inputs were used by the canonical QRAFT/SIESTA M8-C acceptance route.
They intentionally use an isolated Fe atom in a large box and Γ-only sampling;
they are not production convergence recommendations.

- `fe_atom_soc_z.fdf`: `DM.InitSpin 1 + 0.0 0.0`.
- `fe_atom_soc_x.fdf`: `DM.InitSpin 1 + 90.0 0.0`.
- Both require SIESTA 5.4.2 `Spin spin-orbit` and a separately hash-verified,
  fully-relativistic PBE **PSML** pseudo.

The scalar-relativistic M8-A/B Fe pseudo is deliberately not listed as an SOC
input. Real SIESTA 5.4.2 acceptance recorded the `spin-orbit+offsite`,
eight-component stdout dialect; the engine parser requires its explicit
runtime SOC evidence as well as the labelled Mulliken vector table.
