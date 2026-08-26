# M10 HPC portability / production acceptance

Status: `IN_PROGRESS`. M10 validates a real two-node Slurm implementation; it
does not create a new execution authority or a generic cluster configuration
system.

Build an unresolved discovery bundle locally:

```powershell
python tools/build_yoltla_m10_acceptance.py --output .\qraft-m10-discovery
```

It contains a byte-identical generated scientific fixture and zero scientific
`submit.slurm` files. Its login probe is Bash-only and records raw scheduler,
Python, environment mechanism, SIESTA, and launcher observations. It remains
usable when login-node Python is missing or older than 3.11.

Analyze raw evidence on a compatible Python >=3.11 machine and review separate
`scheduler_selection.json` and `runtime_selection.json` artifacts. The runtime
artifact binds Python >=3.11, SIESTA, srun placement, and (when accepted) Hydra
executable, arguments, bootstrap, and replay commands to current evidence.
PATH selections with an empty environment setup are valid.

Render only with both reviewed artifacts:

```powershell
python tools/build_yoltla_m10_acceptance.py `
  --output .\qraft-m10-resolved `
  --scheduler-selection .\scheduler_selection.json `
  --runtime-selection .\runtime_selection.json
```

Missing evidence, unsupported human selections, a too-old Python, an absent
SIESTA, or unavailable required Hydra fail closed as
`M10_RUNTIME_PROFILE_UNRESOLVED`. Scheduler selections may omit account/QoS
only when current evidence explicitly supports Slurm defaults; generated Slurm
directives are then omitted.

See [RUNBOOK.md](RUNBOOK.md) for the mandatory discovery, review, preflight,
real-smoke, and continuation gates. Historical values are evidence only, never
executable defaults.
