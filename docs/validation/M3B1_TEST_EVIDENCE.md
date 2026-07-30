# M3B1 test evidence

Development followed the required order. Real failure evidence was added first. The initial `SLURM_SUBMIT_DIR` suite then failed 5/5 against the old renderer; the package suite initially failed during collection because the generic packager did not exist. After the minimal fixes, M3B1 passes 11/11 and the complete repository passes 198/198 with 0 failures and 0 errors.

The runtime regression simulates a script copied under `var/spool/slurm/job12345/slurm_script`, points `SLURM_SUBMIT_DIR` to an independent package root, and proves that `evidence/`, `work/`, and `results/` appear only under that root. It emits `SLURM_SUBMIT_DIR_RUNTIME_FIX_PASS` and `SPOOL_PATH_REGRESSION_TEST_PASS`.

The ZIP was extracted into a new temporary directory and its independent verifier emitted `M3B1_PACKAGE_HASHES_VERIFIED`, `M3B1_PSEUDOPOTENTIAL_VERIFIED`, `M3B1_GEOMETRY_VERIFIED`, and `M3B1_PACKAGE_VERIFIED`.
