# M3B1 real failure analysis

The sanitized real evidence for job `778835` records `FAILED`, exit code `1:0`, elapsed `00:00:01`, node `nc65`, account `vini`, partition `q1h-20p`, and QoS `normal`. SLURM accepted and dispatched the job, created stdout/stderr, and supplied terminal accounting. It is preserved under `tests/fixtures/m3b1/real_failed_job_778835/` and is never classified as approved execution.

The confirmed failure was `mkdir: cannot create directory '/var/spool/slurm/evidence': Permission denied`. The old generated script derived its root from `BASH_SOURCE[0]`; SLURM ran a spool copy, so the computed root was `/var/spool/slurm`.

Executable SLURM rendering now requires nonempty, existing `SLURM_SUBMIT_DIR`, resolves it canonically, requires `package_manifest.json`, exports `ROOT`, creates only `$ROOT/evidence`, `$ROOT/results`, and `$ROOT/work`, and changes into that verified root. Missing, nonexistent, or manifest-free roots stop with exit code 2.
