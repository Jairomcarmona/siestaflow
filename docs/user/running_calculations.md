# Running calculations

The installed runtime and a campaign are different products. Install QRAFT
once. A portable campaign contains its manifest/configuration, DAG, FDF,
geometry, pseudopotentials, scientific inputs and evidence/results.

The current `single_fdf` layout is:

```text
.qraft-runs/
    qraft.out
    events.jsonl
    session.json
    SCIENTIFIC_ID/
        state.json
        ATTEMPT_ID/
            plan.json
            attempt.json
            stdout.txt
            stderr.txt
            staged scientific inputs
```

Use `qraft validate` and `qraft plan` before `qraft run`. QRAFT never calls
`sbatch` for the single-FDF installed route; allocation-required launchers must
run inside a compatible allocation. A technical PASS is evidence that process,
parser, termination and required-artifact rules passed—not that the physical
model is correct.

Standalone controller packages are retained only for deployment environments
where the installed path is unavailable.
