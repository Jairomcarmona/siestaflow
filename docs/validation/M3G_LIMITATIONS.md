# M3G limitations

- No real SIESTA, MPI, SSH, SLURM, or `sbatch` action was performed. A real SIESTA smoke remains pending separate authorization and verified remote evidence.
- Yoltla is still `REMOTE_EVIDENCE_PENDING`; the canonical profile remains null/missing.
- Schema `1.0` is enforced by the Python loader rather than a published JSON Schema document.
- JSON-compatible YAML works without optional packages; general YAML syntax requires PyYAML to be installed.
- Controlled FDF mutation currently renders `Mesh.Cutoff` and diagonal `kgrid.MonkhorstPack`; other parameters require a new generic renderer and tests, not a project branch.
- PSML staging uses a conservative header marker and PSF staging checks non-empty readable content; it does not perform a full format-schema validation.
- Examples contain no redistributable pseudopotential binary. Users must supply authorized external files.
- The Birnessite structure is a non-scientific technical fixture, not the audited M1 geometry and not publishable evidence.
- The existing M3 deliverable remains a human-operated preview; M3G does not continue to M3B or M4.
