# M8-C Real Full Spin-Orbit Coupling Acceptance

Baseline: `12c5f139f5e66a82992b312dfc45d6701b6bdb43` on
`fix/qraft-m7-scientific-correctness`.

## Environment and scientific input

- SIESTA 5.4.2: `/home/jmc/.local/siesta-5.4.2-openmpi/bin/siesta`.
- Open MPI 4.1.6: `/usr/bin/mpirun`; canonical QRAFT execution used 4 ranks.
- Source collection: `C:\Users\Jairo\Downloads\nc-fr-04_pbe_stringent_psml_FULLRELATIVISTA`.
- Selected input: `Fe.psml`, 242759 bytes, PSML 1.1, Fe, PBE.
- SHA-256: `8942bf3be4d088dbf151e47bb9b434d9606a27510a122298c0b92275a74bb9ab`.
- Classifier: `FULLY_RELATIVISTIC`, from `relativity=dirac`, `spin-orbit` and
  `lj` projector sets, and `l`/`j` projector evidence.
- M8-A/B scalar Fe control SHA-256:
  `6b540d480fbdf34ef2058028ed6a6d47fc818f9ead7ea31e496720420ab44e12`.
  It is distinct from, and rejected for, M8-C SOC.

## Canonical SOC static acceptance

Both static inputs used `Spin spin-orbit`, `Charge.Mulliken end`, the
fully-relativistic PSML above, and canonical QRAFT/OpenMPI-4 execution.

| Case | Result | ScientificIdentity | Requested direction | Observed Mulliken vector |
| --- | --- | --- | --- | --- |
| SOC-Z | PASS; exit 0; SCF 55 | `dbc7a431ceff7dcf3be3b9eaf2960c5f3094d675cf4a0d22fdceb8464aa95194` | `+ 0.0 0.0` | S=3.997832, Sx=0, Sy=0, Sz=3.997832 |
| SOC-X | PASS; exit 0; SCF 61 | `362f0f424dc0c08ac50920b7d8aa722118c85a9de3a4846edad0def7570beef6` | `+ 90.0 0.0` | S=3.997832, Sx=3.997832, Sy=0, Sz=0 |

The common execution fingerprint was
`69e7ee6e7ed2e9d007124d9c7bec9c1ae1289043360fcc6b140543d84b9a0178`.
Z and X therefore have distinct ScientificIdentity but equivalent resources.
Focused identity tests also prove SOC differs from otherwise comparable
non-collinear input and that resource-only changes do not affect identity.

The exact SOC-X retry reused `attempt-0001` with the same identity and
execution fingerprint; no second SIESTA calculation was launched. SOC-Z and
SOC-X used distinct workspaces and distinct `.DM` files; SOC-Z's `.DM` was not
staged into SOC-X. No `.ion` file belongs to the scientific input closure.

## Native output and parser

SIESTA 5.4.2 reported `spin-orbit+offsite`, eight spin components, explicit
SOC runtime evidence, and a labelled `Charge.Mulliken` table with `S`, `Sx`,
`Sy`, and `Sz`. QRAFT's parser records the quantity as `mulliken_spin_population`
in electron-charge units; it does not claim an orbital magnetic moment.

The parser was corrected from the synthetic four-component assumption to
accept the real offsite/eight-component dialect only when SOC runtime evidence
is present. It rejects truncated output, missing SOC declaration, wrong mode,
missing component declaration or table header, missing/duplicate atoms,
non-finite components, inconsistent magnitude, conflicting totals, and
corrupted required runtime evidence. Parsed completed stdout was reused after
the correction; no duplicate DFT run was needed.

Scalar-relativistic, unknown, and malformed SOC PSML inputs block before DFT.
Out-of-scope `spin-orbit+onsite`, `Spin.OrbitStrength`, `Spin.Fix`,
`Spin.Total`, `Spin.Spiral`, DFT+U/Hubbard, and
`TimeReversalSymmetryForKpoints true` are rejected.

## Artifact and M6/M7 integration

The real M6 SOC-Z chain completed its numerical scans, trivial one-atom CG
relaxation, and final SCF with MPI-4. It published `qraft.electronic-state`
with `spin_mode=spin-orbit` and a verified `qraft.magnetic-state`:

- final-SCF ScientificIdentity:
  `8e579d55e85cc83230e1126ae5418a2260e8d3fd0c71f829d2ec6ff521079771`;
- state file/content SHA-256:
  `0a09b31956149a47fe37c05d695e1975197356fa6a179547ace3562ced7f3d9a` /
  `a269e10ba495b5b5e79cc3e71daeff25501d1b4bc5fbe0c1e4197dad9be95efa`;
- magnetic artifact file/content SHA-256:
  `399712ea4678116774e1ffdf25f0e97c145b2622e29e4401a6a0ffda519b1075` /
  `ae9bed443dafcf72bb7caba33fb5565a9b7fb9ecc0e1be501e50e3c72deba2dd`.

The artifact binds requested and observed SOC evidence, convergence, parent
identity, final-FDF/stdout hashes, parser provenance, and fully-relativistic
pseudo provenance. Tests using copies show that M7 rejects corrupt artifact
bytes, content hash, source stdout, parent identity, and spin mode. M7 then
successfully prepared independent BANDS, DOS, and PDOS branches from the real
SOC parent. M7.1 `time_reversal=auto` remained unresolved (`None`), and the
SIESTA FDF did not inject `TimeReversalSymmetryForKpoints true`.

The M6 scan is deliberately minimal: 50/53 meV basis (selected 53), 100/110
Ry mesh (selected 110), and 1x1x1/2x2x2 k-points (selected 2x2x2), each with
the existing 0.10 eV/atom and consecutive-one criterion. These parameters
validate QRAFT/SIESTA SOC integration and are not production SOC convergence
recommendations.

## Regression and architecture gates

- Native focused suite: 63 passed, 1 skipped, 0 failed in 19.92 s.
- M8-A/M8-B compatibility is covered by the focused native suite; the
  historical native identity remains
  `8e8723a8216fd0f0f6dfb0cbf61ee1da3f7381162878b85431255ef380785522`.
- The WSL value
  `757dcbfef9a93c5a84201c93e845a9282bcebc633ff76b73ba47ac0dddac4fd4`
  remains a portability observation only.
- Native full regression, once after the final production change:
  `python -m pytest -q --basetemp="C:\\Users\\Jairo\\Downloads\\SIESTAFLOW_CONTEXT\\qraft-m8c-native-full-basetemp-20260824" -p no:cacheprovider`
  completed with 654 passed, 1 skipped, 0 failed, pytest duration 244.09 s,
  PowerShell duration 245.406123 s, and exit 0.
- Final protected diffs against the baseline are empty for core, contracts,
  generic capability runtime, runtime composition, scheduler, and launcher.

Computational settings are system-acceptance fixtures and are not production
SOC or magnetic-anisotropy convergence recommendations.
