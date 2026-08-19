# Execution profiles

Profiles contain deployment policy, never scientific parameters. Resolution
searches project `.qraft/profiles/` before user
`~/.config/qraft/profiles/`. An explicit path or CLI override wins.

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

## Generic SLURM/Hydra (`cluster.toml`)

```toml
schema_version = "1.0"
name = "cluster"
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
arguments = []

[engine]
executable = "siesta"
arguments = []
```

Inspect with `qraft profile list`, `qraft profile show NAME`, and
`qraft profile validate NAME`. Then use `--profile NAME`. Profile capacity is
validated after overrides. Modules are documented setup instructions; QRAFT
does not execute arbitrary module shell commands as part of profile loading.

Precedence is defaults < user/project config < profile < recipe < REPL < CLI.
No cluster or partition is built into QRAFT.
