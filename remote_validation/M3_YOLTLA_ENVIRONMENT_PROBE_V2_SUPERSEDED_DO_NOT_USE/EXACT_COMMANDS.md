# Exact commands for Yoltla — V2

Run after manually transferring and extracting this directory on Yoltla:

```bash
cd M3_YOLTLA_ENVIRONMENT_PROBE

python3 verify_local_package.py

chmod u+x   run_login_probe.sh   inspect_probe_job.sh   collect_probe_results.sh   scripts/*.sh   scripts/*.py

./run_login_probe.sh

python3 prepare_scheduler_probe.py   --login-evidence evidence/login_probe/summary.json   --output generated/submit_environment_probe.slurm

bash -n generated/submit_environment_probe.slurm

python3 scripts/validate_embedded_python.py   generated/submit_environment_probe.slurm

sed -n '1,240p' generated/submit_environment_probe.slurm
```

DETENERSE PARA INSPECCIÓN HUMANA

Only after human inspection, submit the non-scientific probe manually:

```bash
sbatch generated/submit_environment_probe.slurm   | tee evidence/scheduler_probe/sbatch_submission.txt

JOB_ID=$(awk '/Submitted batch job/{print $NF}'   evidence/scheduler_probe/sbatch_submission.txt)

./inspect_probe_job.sh "$JOB_ID"
```

Run `./inspect_probe_job.sh "$JOB_ID"` again after the job leaves `squeue`,
until terminal `sacct` evidence is present. Empty `squeue` is never success.
Then set the existing external pseudo directory and collect:

```bash
export PSEUDO_ROOT='/ruta/absoluta/a/psml/auditados'

./collect_probe_results.sh   --pseudo-root "$PSEUDO_ROOT"
```

Manually download the resulting `M3_YOLTLA_ENVIRONMENT_RESULTS_<timestamp>.tar.gz`
through the institutionally approved channel and attach it to Codex. Do not edit
scripts or YAML. Do not run any SIESTA input.
