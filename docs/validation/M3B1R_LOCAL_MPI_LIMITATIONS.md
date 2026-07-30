# M3B1R local MPI limitations

1. This is a WSL2/OpenMPI validation on one laptop. It does not validate
   Yoltla, SLURM, `srun`, inter-node networking, cluster modules, scheduler
   accounting, or cluster performance. No SSH, Yoltla, SLURM, or `sbatch`
   action occurred.

2. WSL exposed 7.4 GiB RAM and 2.0 GiB swap. Running three native CTest cases
   concurrently allowed three four-rank SIESTA processes to overlap and caused
   a kernel-recorded OOM. The final complete test pass was therefore run one
   test at a time with `OPENBLAS_NUM_THREADS=1` and `OMP_NUM_THREADS=1`. The OOM
   attempt is preserved as evidence, not treated as a SIESTA smoke failure.

3. The complete upstream CTest inventory ended at 715/730 passing. Non-passing
   cases were:

   - intermittent `libgridxc_mpi_test3`, which passes when rerun alone;
   - 13 upstream reference comparisons with reported numerical differences in
     selected energies/forces;
   - `pr_rstxv_mpi4`, which reached its maximum SCF iterations and aborted;
     its dependent verifier was not run.

   No SIESTA source, upstream reference output, or test tolerance was changed
   to manufacture a clean result. These cases do not use the protected C50
   smoke. The target serial, np=2, and np=4 smoke executions all passed, and
   SIESTAFLOW's complete 240-test suite has zero failures/errors.

4. GNU `time` wraps `mpirun`. Its maximum RSS is not a reliable sum of memory
   across all MPI ranks; it is retained as the observed launcher/process-tree
   metric and must not be interpreted as aggregate MPI memory.

5. Energy equality is assessed only at SIESTA's recorded output precision.
   There is no scientific tolerance configured for this smoke; any future
   nonzero delta is review-required until an approved tolerance exists.

6. The parser observes the atom count and number of species from real SIESTA
   output. The label `C` is bound by the external protected smoke specification,
   FDF and PSML hashes rather than inferred from an untrusted output substring.

7. These are intentionally small technical smokes. They do not establish
   scientific convergence, production suitability, or scalability beyond four
   local processes.
