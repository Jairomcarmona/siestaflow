# M8 Integrated Magnetic Workflow Acceptance

This is the integrated closing evidence for M8-D.  It references, and does
not rewrite, the historical M8-A, M8-B, and M8-C acceptance records.

## Closing lineage

- M8-A collinear: `a6b8fcc368e46d2064512ff7c8cf26f8e9bce31d`
- M8-B non-collinear: `12c5f139f5e66a82992b312dfc45d6701b6bdb43`
- M8-C full SOC: `2c56cde21bc7b0aea20aee2c08ee5a8595f93463`

## M8-D integration evidence

- New SIESTA executions: `0`.
- Native M8-A fcc Fe FM and AFM M6 states were re-verified, including their
  FDF, density-matrix, scientific-identity, magnetic-artifact, and stdout
  hash chains.
- Native final total energies: FM `-6890.936315 eV`; AFM `-6890.816388 eV`.
- Difference AFM–FM: `+0.119927 eV` (`+0.059963499999867054 eV/atom`).
- Explicit selection tolerance: `0.001 eV/atom`.
- Result: `SELECTED`, FM uniquely selected.
- Derived selection artifact file SHA-256:
  `a037f09de0dd182d8e22b38591b19d70977f81f810cbfa77cca9976171413362`.
- Derived selection artifact content SHA-256:
  `f728e63a9994e4f6de7006fd90969ae616a1f2d17c18c2905aeb51e420afc317`.

M8-D parses no stdout in the selector.  The SIESTA engine parser provides an
immutable `qraft.final-scf-energy` envelope for historic states, bound to exact
electronic-state, magnetic-state, FDF, identity, and stdout hashes.  Missing,
corrupt, non-converged, ambiguous, or incomparable candidates result in
`REVIEW_REQUIRED`, never a partial selection.  Equal minima within the explicit tolerance result in
`REVIEW_REQUIRED`/`DEGENERATE`.

## Focused regression

The native focused M8-D/M6/M7/M7.1/M8-A/B/C group passed:

```text
79 passed in 16.01s
```

The test set covers native final-energy parsing, unique three-candidate
FM/AFM1/AFM2 ranking, tie handling,
missing evidence, state/magnetic/identity/energy hash rejection, pseudo and
numerical-context incompatibility, order invariance, M6 state publication,
M7 verification, M7.1 conservative path behavior, and M8-A/B/C compatibility.

## Native full regression

The single authoritative native regression used an external persistent
base-temp and disabled bytecode/cache-provider output:

```text
python -m pytest -q --basetemp=C:\Users\Jairo\Downloads\SIESTAFLOW_CONTEXT\m8d-final-full-pytest-native-r5 -p no:cacheprovider
```

- Python: `3.13.14`
- pytest: `9.0.3`
- passed: `658`
- skipped: `1`
- failed: `0`
- pytest duration: `230.18 s`
- PowerShell elapsed: `231.4969103 s`
- exit: `0`

## Architecture and formal status

No core, contracts, generic capability runtime, runtime composition,
scheduler, launcher, attempt/recovery, DAG primitive, or execution authority
changed.  M8-D adds only engine-owned final-energy evidence and a protocol-only
selection artifact.

- M8-D: `CLOSED`
- M8: `CLOSED`
- M9: `NOT_STARTED`
