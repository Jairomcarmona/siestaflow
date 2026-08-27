# M10 manual Yoltla runbook

**Manual sbatch only.** No M10 submission begins until a human has reviewed
current scheduler and runtime evidence.

## Discovery, selection, and resolved rendering

Build the unresolved bundle locally, transfer it to the shared login-node path,
then run only the Bash raw probe:

```bash
cd /shared/path/qraft-m10-discovery
bash scheduler_discovery/run_login_probe.sh
# Completion is: LOGIN_RAW_PROBE_COMPLETE:<path>
```

The raw probe does not require Python, `module`, Conda, or Spack. It makes no
module changes. Review its module availability files; they are not executable
authority. If a reviewer chooses evidence-observed module names, run the
isolated Bash candidate probe (it never submits a job or launches ranks):

```bash
bash scheduler_discovery/run_runtime_candidate_probe.sh \
  --raw scheduler_discovery/evidence/login_probe/raw \
  --python-module <exact-observed-python-module> \
  --siesta-module <exact-observed-siesta-module>
```

It refuses module names absent from raw evidence, records module setup and
executable evidence, and leaves the calling shell unchanged. Stop if it fails.
If the login Python is absent or too old, transfer
`scheduler_discovery/evidence/login_probe/raw` and any verified probe evidence
to a local or compatible remote machine with Python >=3.11.

On that compatible machine, analyze the immutable raw evidence and create the
two reviewed selections:

```bash
python3 scheduler_discovery/build_login_summary.py \
  --raw scheduler_discovery/evidence/login_probe/raw \
  --runtime-probe scheduler_discovery/evidence/login_probe/runtime_candidate_probe \
  --output login_summary.json
python3 scheduler_discovery/resolve_m10_scheduler.py \
  --login-evidence login_summary.json --output scheduler_selection.json
# Inspect login_summary.json and copy only its reviewed executable paths.
# Do not omit these selections when multiple candidates are present.
python3 scheduler_discovery/resolve_m10_runtime.py \
  --login-evidence login_summary.json \
  --python <observed-module-python-path> \
  --siesta <observed-module-siesta-path> \
  --srun <observed-srun-path> \
  --hydra <observed-hydra-path> \
  --require-hydra \
  --output runtime_selection.json
cat scheduler_selection.json runtime_selection.json
```

If scheduler evidence has multiple candidates, choose only an evidence-backed
account/partition/QoS with the resolver’s explicit arguments. A reviewed
runtime choice may use PATH with `environment_setup: []`, or only a verified
module probe. Hydra is eligible only when its selected module environment
actually exposes it and establishes its bootstrap evidence. Historical values
are never defaults. A summary that contains both login-PATH and verified MODULE
Python candidates is intentionally ambiguous until the reviewer supplies the
observed executable paths above; the resolver does not rank or prefer them.

**HUMAN REVIEW GATE:** transfer the exact reviewed selection files to the
local rendering machine. Render with both; either omitted file fails closed.

```powershell
python tools/build_yoltla_m10_acceptance.py `
  --output <resolved-output> `
  --scheduler-selection scheduler_selection.json `
  --runtime-selection runtime_selection.json
```

## Compute-node preflight

Transfer and extract the resolved bundle to the shared submission directory.
The preflight replays the reviewed runtime selection inside a two-node batch
allocation, verifies the shared marker and manifest on both hosts, checks the
selected Python >=3.11 and SIESTA visibility, explicitly proves 64 `srun`
ranks at 32 ranks/node, and runs the selected Hydra harmless hostname launch.
It does not execute `smoke.fdf` or SIESTA.

```bash
cd /path/to/qraft-m10-yoltla-bundle
sbatch --test-only preflight/submit_m10_preflight.slurm
sbatch preflight/submit_m10_preflight.slurm
# Wait for terminal state; inspect evidence/preflight.<job-id>.txt and placement evidence.
```

**HUMAN GATE:** only after a successful non-scientific preflight may the two
independent real SIESTA technical smokes run (Hydra, then srun).

```bash
cd packages/hydra/QRAFT_M10_MULTINODE_SIESTA_TECHNICAL_ACCEPTANCE
python3 verify_package.py && sbatch --test-only submit.slurm && sbatch submit.slurm
cd ../../srun/QRAFT_M10_MULTINODE_SIESTA_TECHNICAL_ACCEPTANCE
python3 verify_package.py && sbatch --test-only submit.slurm && sbatch submit.slurm
```

## CONTINUATION JOB #1

From the continuation package root, run `sbatch --time=00:01:00 submit.slurm`.
After terminal `sacct` evidence, confirm runtime `INTERRUPTED`, `STAGE_A`
`COMPLETED`, no `STAGE_B` attempt, and the preserved first attempt. The
controlled worker exit may be nonzero.

**HUMAN GATE:** do not submit Job #2 until these conditions have been reviewed.
Do not copy the package or alter its runtime selection/configuration.

## CONTINUATION JOB #2

From the exact same root, run `sbatch --time=00:03:00 submit.slurm`. Confirm
`STAGE_A` `REUSED`, `attempt-0001` preserved, `STAGE_B` completed, final runtime
`COMPLETED`, and both Slurm job IDs in allocation history.
