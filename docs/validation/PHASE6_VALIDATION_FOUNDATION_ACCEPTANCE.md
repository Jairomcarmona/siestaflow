# Phase 6 validation foundation acceptance

Status: `IMPLEMENTED_LOCAL_ACCEPTANCE`

Date: 2026-07-30

## Accepted vertical

- Strict, versioned SIESTA 5.4.2 rule catalog with a canonical SHA-256.
- Core Contracts `RULE_PROVIDER` plugin boundary with no import-time global
  registration.
- Contextual FDF validation layered over the lossless parser and structural
  validator.
- Strict external validation profiles for periodicity, requested Bader output,
  and project-defined cost-review limits.
- Read-only `input rules`, extended `input validate`, and
  `workflow preflight` commands.
- Hash-bound workflow findings for every external SIESTA FDF artifact.

## Acceptance evidence

Local automated tests cover:

- stable catalog loading and capability-registry resolution;
- scalar type, unit, lattice and Monkhorst-Pack failures;
- charged-periodic and dipole-correction review;
- D3 periodicity ambiguity and explicit-axis removal of that warning;
- DFT+U linear-response classification and missing-projector blocking;
- requested Bader output, density-grid review, and policy cost alerts;
- strict profile parsing;
- CLI JSON contracts, exit codes, artifact hashes, and zero filesystem
  mutation during workflow preflight.

The validator was also exercised against the 32-atom potassium-birnessite
common FDF retained from the real Yoltla campaign package. All previously
unregistered, officially documented SIESTA 5.4.2 keywords in that input were
added to the registry. The remaining findings were the expected reviews for
stage-specific values absent from the shared include fragment.

## Scientific and operational boundary

This is local software acceptance, not scientific validation and not Yoltla
runtime acceptance. The validator does not prove convergence, stability,
physical representativeness, scalability, or agreement with experiment. It
does not select scientific parameters, resolve arbitrary includes, execute
SIESTA, submit Slurm jobs, or authorize a run.

Heuristic and project-policy rules can emit `REVIEW` only. Deterministic
`FAIL` is limited to registered syntax and mathematical inconsistency;
`BLOCKED` indicates missing declared evidence or output. A version increment
is deferred until additional real campaign evidence is accumulated.
