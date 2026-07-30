# Exact remote commands

```bash
cd M3B1_SURF_GR5X5_REAL_SIESTA_SMOKE
python3 verify_package.py
chmod u+x scripts/*.sh scripts/*.py prepare_smoke_job.py
./scripts/run_login_discovery.sh
cat evidence/login_discovery/runtime_candidates.json
```

STOP FOR HUMAN REVIEW. Select only a SIESTA MPI executable and `srun` recorded
in that evidence. Then generate, but do not submit, the job:

```bash
python3 prepare_smoke_job.py --runtime-candidates evidence/login_discovery/runtime_candidates.json
cat generated/runtime_selection.json
sed -n '1,240p' generated/submit_real_siesta_smoke.slurm
bash -n generated/submit_real_siesta_smoke.slurm
```

STOP FOR HUMAN REVIEW. This package intentionally ends here. A later authorized
phase may submit the reviewed generated file. Do not run `sbatch` in this phase.
