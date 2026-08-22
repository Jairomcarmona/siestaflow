# M4 F03 chained numerical convergence validation

Baseline: `fd855268d8439b5070e5d70e7971332bede2c360`.

The synthetic F03 chain selected `DZP`, `300 Ry`, and `[3, 3, 3]` through
three stage-wise canonical F02 campaigns. Typed SCIENTIFIC_ARTIFACT selection
envelopes were reloaded and hash-bound into inherited downstream parameters.
Rendered mesh FDFs contained `PAO.BasisSize DZP`; rendered k-point FDFs also
contained `Mesh.Cutoff 300 Ry`.

M4-01 through M4-10 passed. Recovery reused all stage attempts and retained
selection/profile artifact hashes. Final full suite: `568 passed`.

Closing commit: `feat: add F03 chained numerical convergence`.
