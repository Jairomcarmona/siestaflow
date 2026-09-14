# M7.1 — Crystallographic high-symmetry band paths

M7.1 adds reproducible construction of the existing M7 `BandPathSpec`.  It
does not add an executor, a SIESTA renderer, a runtime, or a recovery path.
The composition is deliberately narrow:

```text
verified M6 final geometry -> BandPathRequest -> SymmetryPathProvider
-> BandPathProposal -> scientific safety policy -> BandPathSpec -> M7
```

`qraft.band_paths` contains neutral immutable request, structure, segment,
analysis, proposal, provenance, and policy models.  The optional generic
`SeekPathProvider` is isolated in `qraft.symmetry`; no SeeK-path or spglib
object is exposed to the QRAFT domain or the SIESTA adapter.

## Public Python API

The supported reusable entry points are `BandPathMode`, `BandPathRequest`,
`BandPathSegment`, `BandPathProposal`, `CrystalStructure`, `BandPathPlanner`,
`SymmetryPathProvider`, `ProviderPath`, and `SymmetryAnalysis` from `qraft`.
A provider implements `SymmetryPathProvider.generate(structure, request)` and
returns neutral `ProviderPath` and `SymmetryAnalysis` values.  Test or site
providers can therefore replace SeeK-path without changing M7.

`ElectronicPropertiesProtocol.prepare` and `.run` accept either the legacy
`BandPathSpec` or a `BandPathRequest`, with an optional `band_path_provider`.
For a request, the protocol derives the structure from the already verified
M6 final FDF and rejects a supplied structure whose hash differs from that
geometry.  This preserves M6 ScientificIdentity and the parent `.DM` rather
than silently standardizing the electronic system.

There is no M7.1 CLI in V1.  The existing CLI has no M7 protocol command tree
to share without creating a second execution path.  The Python API is the
single backend for a future CLI.

## Modes

### MANUAL

MANUAL accepts explicit `BandPathSegment` values.  It neither loads a provider
nor analyses symmetry.  Labels, reciprocal coordinates, segment order, point
counts, and `ReciprocalLatticeVectors` scale are preserved.  MANUAL is the
investigator's final authority and remains available without optional
dependencies.

Segments are primary data, not a flattened vertex list.  Thus
`Γ-X-U | K-Γ-L` is represented as four continuous segments.  The SIESTA
compiler starts the second group with a count of `1`, so it does not create an
unrequested `U-K` line.

### SUGGEST

SUGGEST is non-destructive: it produces JSON-serializable
`BandPathProposal` evidence and does not materialize M7, run SIESTA, create a
DM, or modify an electronic-state artifact.  Supercells and unstable symmetry
produce `REVIEW`, retaining the proposed metadata and warnings for a scientist
to evaluate.

### AUTOMATIC

AUTOMATIC uses the HPKOT convention through SeeK-path, then materializes the
approved proposal through the existing `BandPathSpec` and M7 renderer.  It
blocks rather than guessing when the provider is unavailable, the geometry is
invalid, symmetry analysis fails or changes across tolerances, a supercell is
detected, a structure transformation would be required, path topology is
invalid, or parent M6 geometry continuity cannot be preserved.

`AUTOMATIC != silent scientific decision without evidence.`

## Symmetry and density policy

Install the optional implementation with `qraft[symmetry]`; this installs
SeeK-path (and its spglib dependency).  Absence is reported as a controlled
`BLOCKED` proposal, never as a raw `ImportError`.

The V1 convention is HPKOT.  A request records `symprec`, optional
`angle_tolerance`, `reference_distance` in reciprocal-space length units, and
`time_reversal` (`auto`, `true`, or `false`). Explicit values are passed to the
provider. `auto` resolves only from explicit verified M6 non-magnetic evidence;
when that evidence is unavailable SUGGEST returns `REVIEW` and AUTOMATIC is
`BLOCKED` with `TIME_REVERSAL_UNRESOLVED`. This leaves M8 magnetism/SOC free to
supply its own policy rather than inheriting a hidden default.

The planner evaluates `0.1 * symprec`, `symprec`, and `10 * symprec` and
compares space-group number, Bravais lattice, supercell status, and path
topology.  A change is `SYMMETRY_AMBIGUOUS`: SUGGEST returns `REVIEW` and
AUTOMATIC returns `BLOCKED`.  It never chooses the "prettiest" tolerance.

SeeK-path uses `get_path_orig_cell()` and `get_explicit_k_path_orig_cell()`:
the M6 input-cell reciprocal basis is retained and the parent structure is not
standardized. Explicit intervals are interpreted as `[start, stop)`, preserving
both shared vertices and path breaks. QRAFT records SeeK-path `point_coords`,
implicit path, explicit segments, inversion state, and augmentation in the
neutral provenance. No crystal-name path tables are embedded in QRAFT.

## Provenance and continuity

Every proposal has a deterministic SHA-256 over its canonical JSON.  The
provenance records mode, provider and spglib versions, convention, geometry
hash, requested and tested tolerances, symmetry results and stability,
time-reversal policy, space group, Bravais lattice, primitive mapping,
supercell state, ordered segments, discontinuities, reference distance, and
point counts.  AUTOMATIC also persists the compiled `BandPathSpec` and its
hash under the prepared M7 BANDS source.

If a provider needs a structurally different primitive or standardized cell,
V1 AUTOMATIC blocks.  A new structure would require a new ScientificIdentity,
SCF, DM, and subsequent band calculation; that is intentionally outside M7.1.
