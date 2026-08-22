# M4 F03 chained numerical convergence validation

Hotfix baseline: `2613159296f75dbb94d0b78806b9009c49d05ae2`.

The synthetic F03 chain selected `DZP`, `300 Ry`, and `[3, 3, 3]` through
three stage-wise canonical F02 campaigns. Typed SCIENTIFIC_ARTIFACT selection
envelopes were reloaded and hash-bound into inherited downstream parameters.
Rendered mesh FDFs contained `PAO.BasisSize DZP`; rendered k-point FDFs also
contained `Mesh.Cutoff 300 Ry`.

The surgical invariant hotfix additionally verifies that a technically failed
stage cannot propagate despite a converged scientific decision, inherited
`basis_energy_shift` values retain the exact upstream `meV` unit, loose
pseudopotential mismatches are rejected before execution, and blocked results
retain basis, mesh, and k-point evidence through the blocking stage.

M4 remains `CLOSED`; M5 remains `NOT_STARTED`. The hotfix target passed `7`
tests, focused regression passed `26` tests, and the final full suite passed
`572` tests. Recovery reused all stage attempts and retained selection/profile
artifact hashes.

Closing hotfix commit: `fix: enforce M4 chained convergence invariants`.
