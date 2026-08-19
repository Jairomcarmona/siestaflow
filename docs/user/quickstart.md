# Quickstart

This route performs no hidden submission and requires no Python editing.

```bash
qraft --version
qraft env
qraft config --profile local
qraft validate calc.fdf --profile local
qraft plan calc.fdf --profile local
qraft run calc.fdf --profile local
qraft status
qraft resume
```

1. Put `calc.fdf`, its includes, geometry and pseudopotentials together under a
   project directory.
2. Create `.qraft/profiles/local.toml` using the profiles guide.
3. `env` inspects installed external capabilities.
4. `config` explains resolved values and provenance.
5. `validate` checks the FDF, inputs, profile, resources and writable paths.
6. `plan` prints the DAG and explicitly submits nothing.
7. `run` performs the same preflight, creates immutable attempts, and writes
   `.qraft-runs/qraft.out` plus machine evidence.
8. `status` reads persisted state. `resume` reloads `.qraft-runs/session.json`
   and reuses an already valid attempt when possible.

The execution contract is at-least-once with immutable attempts and idempotent
recovery; it is not an exactly-once guarantee.
