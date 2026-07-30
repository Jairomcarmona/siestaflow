# M3B1 limitations

- No SSH, remote MPI, SLURM, `sbatch`, or SIESTA command was executed by Codex.
- The package prepares a real scientific calculation, but no scientific result exists yet.
- The intended run is a technical single-point smoke; energy, electronic structure, convergence quality, and graphene properties must not be interpreted.
- Scheduler memory remains unspecified because no binding memory request was provided; SLURM site policy will govern it.
- SIESTA executable and MPI launcher availability must be confirmed by the included login-only discovery before human submission.
- The received M3B1 prompt attachment ends abruptly during section 11; requirements beyond that truncation were not invented.
