# Probe checklist — V3

- [ ] A clean V3 directory was used; no earlier-revision files were mixed
- [ ] Account, partition, and QoS selection is supported by scheduler evidence
- [ ] Package hashes verified before execution
- [ ] Direct Python, Bash, SLURM, and embedded Python syntax verified
- [ ] Login probe completed without persistent environment changes
- [ ] Generated scheduler script inspected by a human
- [ ] Job used one node/task and no scientific input
- [ ] Job ID and submission stdout preserved
- [ ] `sacct` shows terminal State and ExitCode
- [ ] SIESTA discovery contains no FDF execution
- [ ] MPI launcher evidence captured
- [ ] Work/project/scratch visibility captured
- [ ] Every manifest-declared pseudopotential was read in place and hash checked
- [ ] Result bundle hashes verified locally before import
