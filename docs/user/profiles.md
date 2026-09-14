# Execution profiles

Profiles describe deployment policy, never scientific parameters. QRAFT looks
first in project `.qraft/profiles/` and then in
`~/.config/qraft/profiles/`. An explicit file path also works. For profiles
with the same filename, the project copy wins.

Use the canonical profile commands:

```bash
qraft setup profile list
qraft setup profile show NAME
qraft setup profile validate NAME
qraft setup config --profile NAME
```

`qraft profile ...` remains a compatibility alias. Structural validation does
not reserve resources or run SIESTA.

## Local OpenMPI (`local.toml`)

```toml
schema_version = "1.0"
name = "local"
scheduler = "local"
partition = "local"
nodes = 1
cpus_per_node = 4
mpi_ranks = 4
cpus_per_rank = 1
walltime = "00:10:00"

[launcher]
name = "openmpi"
command = ["mpirun"]
arguments = []

[engine]
executable = "siesta"
arguments = []

[environment_setup]
module_commands = []
variables = { OMP_NUM_THREADS = "1" }
```

## Slurm with `srun` (`slurm-srun.toml`)

This is the preferred generic Slurm profile. Replace every site-specific value
before use.

```toml
schema_version = "1.0"
name = "slurm-srun"
scheduler = "slurm"
partition = "compute"
nodes = 2
cpus_per_node = 32
mpi_ranks = 64
cpus_per_rank = 1
walltime = "01:00:00"

[launcher]
name = "srun"
command = ["srun"]
arguments = []

[engine]
executable = "siesta"
arguments = []

[environment_setup]
module_commands = [
  "module purge",
  "module load siesta/5.4.2",
  "module load python/3.12",
]
variables = { OMP_NUM_THREADS = "1" }
```

The allocation must grant exactly 2 nodes, 64 tasks, 32 tasks per node and one
CPU per task for this example. The `srun` adapter adds the placement arguments;
do not duplicate `--nodes`, `--ntasks`, `--ntasks-per-node` or
`--cpus-per-task` in `launcher.arguments`.

## Slurm with Hydra (`slurm-hydra.toml`)

Use Hydra only when it is the MPI launcher approved by the site and passwordless
SSH between allocated compute nodes is supported. The launcher requires exactly
one explicit bootstrap pair; this example uses the repository-validated `ssh`
value.

```toml
schema_version = "1.0"
name = "slurm-hydra"
scheduler = "slurm"
partition = "compute"
nodes = 2
cpus_per_node = 32
mpi_ranks = 64
cpus_per_rank = 1
walltime = "01:00:00"

[launcher]
name = "hydra"
command = ["mpiexec.hydra"]
arguments = ["-bootstrap", "ssh"]

[engine]
executable = "siesta"
arguments = []

[environment_setup]
module_commands = []
variables = { OMP_NUM_THREADS = "1" }
```

QRAFT derives Hydra's `-hosts`, `-np` and `-ppn` values from the active Slurm
allocation and the profile. Do not add those placement options to the profile.

## Resolution and modules

For the installed FDF route, the effective order is defaults, profile, project
configuration, recipe and CLI overrides; each later layer can replace an
earlier value. Profile capacity is checked after resolution.

`environment_setup.variables` is passed to launched processes. In this
installed route, `module_commands` is recorded for inspection but is not
executed. Load the declared modules before activating/running QRAFT, both in an
interactive allocation and in a batch script. See
[`docs/user-guide/11-slurm-hpc.md`](../user-guide/11-slurm-hpc.md) for a complete
Slurm run.
