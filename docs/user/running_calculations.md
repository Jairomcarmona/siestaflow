# Running calculations

Install QRAFT once in a virtual environment visible to the compute nodes. A
calculation remains separate from the installed package: it contains the FDF,
included files, geometry, pseudopotentials and any scientific configuration.

For one complete SIESTA FDF, the normal sequence is:

```bash
RUNS_ROOT="$SCRATCH/qraft/$USER/calculation-001"
qraft check calc.fdf --profile slurm-srun --runs-root "$RUNS_ROOT"
qraft inspect plan calc.fdf --profile slurm-srun
qraft run calc.fdf --profile slurm-srun --runs-root "$RUNS_ROOT"
qraft status --runs-root "$RUNS_ROOT"
qraft results --runs-root "$RUNS_ROOT"
```

`check` and `inspect plan` do not submit a job or run SIESTA. Launchers tied to
Slurm (`srun` and Hydra) can execute only inside a compatible allocation. QRAFT
does not call `sbatch` for this installed FDF route; use `salloc` or place the
commands in a batch script as described in the
[Slurm/HPC runbook](../user-guide/11-slurm-hpc.md).

Use a unique, persistent `RUNS_ROOT` for each independent calculation. The
current canonical single-FDF layout is:

```text
RUNS_ROOT/
    qraft.out
    events.jsonl
    session.json
    runtime/
        RUNTIME_KEY/
            evidence/
                workflow_events.jsonl
            state/
                workflow_runtime.json
            work/
                run_siesta/
                    attempt-0001/
                        attempt.json
                        input.fdf
                        stdout.txt
                        stderr.txt
                        staged scientific inputs and SIESTA outputs
```

The `RUNTIME_KEY` depends on the scientific and execution identities. A
CampaignSpec protocol can add campaign-level state and
`campaign-result.json`; do not assume that file exists for every single-FDF
run. Use `qraft results` to inventory files actually recorded.

To continue after an interruption, obtain another compatible allocation, load
the same modules and virtual environment, and run:

```bash
qraft status --runs-root "$RUNS_ROOT"
qraft resume --runs-root "$RUNS_ROOT"
```

The saved `session.json` supplies the original target and execution inputs.
Completed attempts are immutable and can be reused; QRAFT creates another
attempt only when recovery requires one. Preserve the complete runs root and
do not edit attempt evidence by hand.

A technical `PASS` means that process exit, parsing, termination and required
artifact rules passed. It is not a claim that the physical model, convergence
criteria or scientific interpretation are correct.

Standalone controller packages remain a deployment fallback for environments
where the installed path is unavailable; they are a separate advanced flow.
