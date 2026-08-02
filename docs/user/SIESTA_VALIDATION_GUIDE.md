# SIESTA input validation

SIESTAFLOW provides an explainable, read-only validation layer for SIESTA
5.4.2 inputs. Its purpose is to catch costly inconsistencies before submission
without pretending to replace numerical convergence studies or scientific
judgment.

## Commands

```powershell
python -m siestaflow.cli input rules --engine-version 5.4.2
python -m siestaflow.cli input validate system.fdf --explain
python -m siestaflow.cli input validate system.fdf `
  --profile validation-profile.json `
  --pseudo-manifest pseudopotentials.json `
  --require-pseudos --json
python -m siestaflow.cli workflow preflight workflow.json `
  --profile validation-profile.json --json
```

All commands above are read-only. Exit `0` means `PASS` or `REVIEW`; exit `2`
means `FAIL` or `BLOCKED`. `REVIEW` never becomes an automatic rejection.

## Decision meanings

- `PASS`: no registered finding requires attention.
- `REVIEW`: the input may be intentional, but the researcher must inspect and
  justify it.
- `BLOCKED`: required evidence or declared project output is absent.
- `FAIL`: a deterministic schema or mathematical consistency check failed.

The report records the rule identifier and version, evidence class, location,
observed values, remediation, source URL, catalog hash, and applied profile
hash. It never grants execution authority.

## Validation profile

Universal syntax checks need no project configuration. Rules whose answer
depends on scientific intent use a strict external profile:

```json
{
  "schema_version": "1.0",
  "profile_id": "birnessite-final-density",
  "periodicity": "bulk",
  "required_outputs": ["bader"],
  "review_limits": {
    "max_kpoints": 400,
    "max_atoms_times_kpoints": 20000
  }
}
```

`periodicity` accepts `unknown`, `molecule`, `chain`, `slab`, or `bulk`.
The only initial required output is `bader`. Cost limits are
researcher-declared review thresholds, not universal physics and not runtime
predictions.

Unknown profile fields and invalid values fail closed. JSON is always
available; YAML requires PyYAML in the preparation environment.

## Built-in rule families

The versioned catalog contains:

- keyword form, scalar type, explicit physical units, and documented enums;
- finite, nonsingular lattice vectors;
- valid three-row Monkhorst-Pack matrices and review of unusual shifts;
- declared context for charged periodic systems and charged slab dipole
  corrections;
- explicit D3 periodic axes when low-dimensional or nonorthogonal geometry
  makes automatic inference ambiguous;
- DFT+U projector context and explicit classification of
  `DFTU.PotentialShift` linear-response tasks;
- presence of requested Bader output and review of the density-grid cutoff;
- project-defined k-point and atom-k-point cost alerts.

The source of engine behavior is the
[official SIESTA 5.4 reference](https://docs.siesta-project.org/projects/siesta/en/5.4/reference/siesta.html).
Rules that are mathematical, project policy, or heuristic review say so
explicitly instead of presenting themselves as manual requirements.

## Deliberate limits

This first vertical does not:

- prove chemical stability, global minima, convergence, scalability, or
  agreement with experiment;
- choose a functional, pseudopotential, Hubbard U, spin state, k-grid, mesh
  cutoff, charge model, or cell;
- infer whether a large calculation is scientifically worthwhile;
- fully validate every row of the flexible `DFTU.Proj` grammar;
- resolve arbitrary `%include` or redirection paths;
- execute SIESTA, submit Slurm jobs, or edit FDF files.

Project-specific chemistry and convergence policies belong in separately
versioned rule plugins or profiles. They must preserve evidence and cannot
silently change scientific inputs.

## Workflow preflight

`workflow preflight` compiles the workflow first. Therefore external paths,
hashes, graph dependencies, and resource placement must be valid before any
FDF is inspected. Findings are then attached to the workflow with:

- the external artifact identifier;
- its SHA-256;
- the source-relative FDF path and line;
- the input ruleset hash.

No lock, state directory, cache, or prepared input is written by preflight.
