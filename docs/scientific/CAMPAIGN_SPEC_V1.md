# CampaignSpec v1

`CampaignSpec` describes the scientific experiment. It deliberately excludes
partition, node count, MPI ranks, launcher, executable and walltime; those
remain in an external `ExecutionProfile` or explicit CLI overrides.

The first functional protocol is a generic one-axis numerical convergence
scan. The same `ParameterSpec` contract supports `fixed`, `scan`, `inherit`,
`auto-suggest` and `disabled`. `auto-suggest` is advisory and is never applied
or executed silently. `inherit` records the evidence source and may bind its
SHA-256 and compatible scientific identity.

```yaml
schema_version: "1.0"
campaign_id: mgo-mesh
engine: siesta
protocol: convergence
system:
  fdf: calc.fdf
parameters:
  mesh_cutoff:
    mode: scan
    values: [200, 250, 300]
    unit: Ry
  basis_size:
    mode: fixed
    value: DZP
criterion:
  metric: energy_per_atom
  delta: 0.001
  unit: eV
  consecutive: 2
```

Inspect before execution:

```bash
qraft validate campaign.yaml
qraft plan campaign.yaml --profile local-wsl
qraft render campaign.yaml --output rendered
qraft run campaign.yaml --profile local-wsl --runs-root runs
```

The SIESTA adapter maps the initial supported axes (`basis_size`,
`basis_energy_shift`, `mesh_cutoff`, and `kpoints`) to concrete FDF semantics.
The core model contains no FDF keyword. Controlled `engine_options.siesta`
entries allow typed scalar extensions without turning the core into a SIESTA
keyword registry.

The contracts can already represent future vacuum/supercell scans, magnetic
configurations, relaxation stages, inherited LR-U values, SOC and custom basis
parameters. Their protocol compilers are intentionally not implemented in v1.
Changing execution placement does not change rendered science or
`ScientificIdentity`; changing any rendered scientific parameter does.
