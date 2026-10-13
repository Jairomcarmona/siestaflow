# Own V-4 regression fixture

`si-fixed.STRUCT_OUT` is the original SIESTA 5.4.2 output from the block-2 Q-3
real EOS reference (Si/PBE/SZP, fixed Mesh.Sizes 30 cubed), retained at
`/home/jmc/.local/state/dftlab-block2/q3/real-eos-002/campaign/reference/runtime/work/reference/attempt-0001/si.STRUCT_OUT`.
It is an additional regression fixture, not a normative vector. Its symmetry
is R-3m (166) at 0.005 Angstrom and Fd-3m (227) at the explicitly approved
0.01 Angstrom. The initial 5.43 Angstrom primitive diamond cell is in the test.
No changes were made to the accepted PRESETS vectors, oracle or tolerances.
