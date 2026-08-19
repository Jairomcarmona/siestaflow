# QRAFT

QRAFT is a declarative, evidence-oriented orchestrator for scientific HPC
campaigns. It turns an input and external execution configuration into a
validated plan, executes through registered launchers, and preserves immutable
attempts plus human-readable and machine-readable evidence.

QRAFT is extensible; **SIESTA is the backend currently implemented and
validated**. QRAFT validates execution mechanics and provenance. It does not
guarantee physical correctness, scientific convergence, a global minimum, an
appropriate pseudopotential, a correct Hubbard U, or universal bitwise
reproducibility.

## Install

Python 3.11 or newer is required. SIESTA, MPI and SLURM are external runtime
capabilities and are not required to install the Python package.

```bash
python -m venv .venv
source .venv/bin/activate
pip install qraft-0.2.0-py3-none-any.whl
qraft --version
qraft --help
```

For development only:

```bash
git clone https://github.com/Jairomcarmona/siestaflow.git
cd siestaflow
pip install -e '.[dev]'
```

## First calculation

```bash
qraft env
qraft config
qraft validate calc.fdf --profile local
qraft plan calc.fdf --profile local
qraft run calc.fdf --profile local
qraft status
qraft resume
```

Running `qraft` without arguments opens the interactive `qraft>` shell. Profiles
live in `.qraft/profiles/` in a project or `~/.config/qraft/profiles/` for a
user; no Python editing is required.

The authoritative execution record is Event/State/Evidence. `qraft.out` is the
professional human-readable campaign view and CSV files are derived views.

## Supported today

- one-FDF SIESTA planning and execution;
- direct, OpenMPI, SLURM `srun`, and Hydra launcher adapters;
- external JSON/TOML execution profiles;
- immutable attempts, technical validation and idempotent recovery;
- installed mode as the normal deployment path;
- standalone controller bundles as a deployment fallback.

Historical and experimental workflow commands remain available but are not all
part of the stable CLI surface. See [the quickstart](docs/user/quickstart.md),
[CLI contract](docs/user/cli.md), [profiles](docs/user/profiles.md), and
[release checklist](docs/developer/RELEASE_CHECKLIST.md).

The broader historical command surface remains documented in the
[user manual](docs/user/USER_MANUAL.md) and
[CLI reference](docs/user/CLI_REFERENCE.md). Cluster-specific operational
history, including Yoltla, is documentation rather than core policy and remains
in the [Yoltla runbook](docs/operations/YOLTLA_RUNBOOK.md).
