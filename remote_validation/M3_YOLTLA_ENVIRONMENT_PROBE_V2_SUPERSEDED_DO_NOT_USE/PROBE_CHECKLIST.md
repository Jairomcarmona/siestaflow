# Probe checklist — V2

- [ ] Every V1 copy was removed or renamed; no V1/V2 files were mixed
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
