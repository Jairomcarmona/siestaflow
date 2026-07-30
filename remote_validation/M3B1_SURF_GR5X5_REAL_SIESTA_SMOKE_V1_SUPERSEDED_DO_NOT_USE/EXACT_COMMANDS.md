# Exact remote commands

```bash
cd M3B1_SURF_GR5X5_REAL_SIESTA_SMOKE
python3 verify_package.py
chmod u+x scripts/*.sh scripts/*.py
./scripts/run_login_discovery.sh
cat evidence/login_discovery/summary.json
bash -n submit_real_siesta_smoke.slurm
sed -n '1,240p' submit_real_siesta_smoke.slurm
```

STOP FOR HUMAN REVIEW. Confirm that login discovery found a real SIESTA
executable and an MPI launcher. Only then may the one real smoke be submitted:

```bash
sbatch submit_real_siesta_smoke.slurm | tee evidence/sbatch_submission.txt
JOB_ID=$(awk '/Submitted batch job/{print $NF}' evidence/sbatch_submission.txt)
./scripts/inspect_job.sh "$JOB_ID"
```

After terminal `sacct` evidence exists, inspect `results/siesta.out` and
`results/siesta.err`, then run `python3 scripts/collect_results.py`. Do not run
another job, a campaign, an optimization, or any scientific interpretation.
