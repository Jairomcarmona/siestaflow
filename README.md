# QRAFT HPC

The Python distribution is named `qraft-hpc`; the import and command remain
`qraft`. Publication on PyPI is a separate release step; install from the
clone or a locally built wheel as described below. The GitHub repository
currently uses the historical name `siestaflow`; the installation URLs below
are valid for that repository. Internal `siestaflow.*` identifiers are retained
for compatibility with existing artifacts. See the
[naming and compatibility policy](docs/compatibility/naming.md).

Citation metadata is available in [CITATION.cff](CITATION.cff). When reporting
research use, also record the exact release or commit executed. Contributions
follow the [community code of conduct](CODE_OF_CONDUCT.md).

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

Python 3.11 or newer is required. QRAFT supports POSIX/Linux systems. SIESTA,
MPI and SLURM are external programs supplied by the user or HPC site; they are
not installed by the Python package.

Install from a clean clone in a dedicated virtual environment. The unrelated
PyPI project `qraft` shares the import and command names; do not install both
distributions in one environment. When migrating an existing installation,
create a fresh environment using this procedure:

```bash
git clone https://github.com/Jairomcarmona/siestaflow.git
cd siestaflow
python -m venv .venv
source .venv/bin/activate
python -m pip install .
qraft --version
qraft --help
```

For development, replace the install command with:

```bash
python -m pip install -e '.[dev]'
```

A wheel is a build artifact and is not stored in the repository. An
administrator can build one from a clean clone with `python -m build --wheel`,
or prepare an offline wheelhouse with
`python -m pip wheel --wheel-dir wheelhouse .`. Build the wheelhouse on a
Linux system compatible with the target cluster, then install it there with:

```bash
python -m pip install --no-index --find-links /shared/path/wheelhouse qraft-hpc==0.2.0
```

See the [installation guide](docs/user-guide/01-installation.md) for the full
clone, wheel and offline wheelhouse procedures.

## First calculation

Start in a project directory. Generate the campaign template, then edit it
before validation: point `system.fdf` at your real SIESTA FDF and either supply
the referenced pseudopotentials and a valid manifest or remove the example
manifest entry when the FDF resolves them directly. Create or select an
execution profile for the cluster; do not reuse another site's partition,
launcher or executable paths.

```bash
mkdir my-qraft-project
cd my-qraft-project
qraft init campaign.yaml
# Edit campaign.yaml, the FDF and pseudopotential inputs now.
# Create .qraft/profiles/cluster.toml using the profiles guide.
qraft setup profile validate cluster
qraft setup env --profile cluster
qraft check campaign.yaml --profile cluster
qraft inspect plan campaign.yaml --profile cluster
qraft run campaign.yaml --profile cluster --runs-root .qraft-runs
qraft status --runs-root .qraft-runs
qraft results --runs-root .qraft-runs
```

Only run after `check` accepts the inputs and the resolved execution plan.
An `srun` or Hydra profile must run inside a matching scheduler allocation; see
the [Slurm/HPC runbook](docs/user-guide/11-slurm-hpc.md) before submitting work.
Continue with the [campaign quickstart](docs/user-guide/02-quickstart.md) and
the [execution profile guide](docs/user/profiles.md).

Running `qraft` without arguments prints the task-oriented V2 command guide and
exits without prompting. Profiles live in `.qraft/profiles/` in a project or
`~/.config/qraft/profiles/` for a user; no Python editing is required.

The authoritative execution record is Event/State/Evidence. `qraft.out` is the
professional human-readable campaign view and CSV files are derived views.

## Supported today

- one-FDF SIESTA planning and execution;
- direct, OpenMPI, SLURM `srun`, and Hydra launcher adapters;
- external JSON/TOML execution profiles;
- immutable attempts, technical validation and idempotent recovery;
- installed mode as the normal deployment path;
- standalone controller bundles as a deployment fallback.

The installed CLI starts with the core `init`, `check`, `run`, `status`,
`resume`, `results`, and `examples` tasks. Run `qraft --help` for the installed
surface, consult the generated [CLI reference](docs/user/CLI_REFERENCE.md), and
use the [user guide](docs/user-guide/) for task-oriented guidance. Legacy
routes remain available during the compatibility window.

Distribution documentation is available from the repository rather than from
paths assumed to exist beside an installed wheel: [quick start](https://github.com/Jairomcarmona/siestaflow/blob/main/docs/user/QUICK_START.md),
[profiles](https://github.com/Jairomcarmona/siestaflow/blob/main/docs/user/profiles.md),
[`docs/user/CLI_REFERENCE.md`](https://github.com/Jairomcarmona/siestaflow/blob/main/docs/user/CLI_REFERENCE.md),
and the [release checklist](https://github.com/Jairomcarmona/siestaflow/blob/main/docs/developer/RELEASE_CHECKLIST.md).

Historical material remains available by stable repository URL, including
[`docs/user/USER_MANUAL.md`](https://github.com/Jairomcarmona/siestaflow/blob/main/docs/user/USER_MANUAL.md)
and the [`docs/operations/YOLTLA_RUNBOOK.md`](https://github.com/Jairomcarmona/siestaflow/blob/main/docs/operations/YOLTLA_RUNBOOK.md).

## License

QRAFT is distributed under the BSD 3-Clause License. See [LICENSE](LICENSE).
