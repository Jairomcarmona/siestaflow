# Safe publication preparation

This workflow prepares reviewable publication changes under the existing
[development governance](DEVELOPMENT_GOVERNANCE.md). Documentation and naming
preparation do not by themselves establish release readiness or scientific
acceptance. The [naming policy](../compatibility/naming.md) explains which
legacy identifiers must be preserved.

## Back up the source before editing

Start by recording the checkout state and the source commit:

```bash
git status --short
git rev-parse HEAD
git remote -v
```

Preserve unrelated local edits separately. A Git bundle contains reachable
Git history and references, but does not include untracked files, working-tree
edits, Git LFS payloads, external datasets or submodule repositories. Protect
those separately when present; do not assume a source bundle backs up HPC
results or the complete GitHub project configuration.

Create the bundle outside the source tree, using a new destination name that
does not overwrite a previous backup. The following examples assume the
parent directory is an approved backup location and the names are unused:

```bash
git bundle create ../qraft-before-publication.bundle --all
git bundle verify ../qraft-before-publication.bundle
git bundle list-heads ../qraft-before-publication.bundle
git clone ../qraft-before-publication.bundle ../qraft-backup-verification
git -C ../qraft-backup-verification fsck --full
git -C ../qraft-backup-verification rev-parse HEAD
```

Check that the original source commit is available in the restored clone and
that the expected references appear in the bundle. Record the bundle path,
source commit and verification results. Copy the backup to independent
storage for protection against loss of the working disk. A second directory
on that disk provides a recovery copy but does not protect against disk loss.

## Isolate and review the changes

Fetch the intended source branch and inspect its commit before creating an
isolated worktree. These example names must be unused:

```bash
git fetch origin
git rev-parse origin/main
git worktree add -b codex/safe-publication ../qraft-publication origin/main
```

Record the selected base SHA. Keep edits within the approved scope and use
atomic commits. Read the full diff and inspect scope before committing:

```bash
git status --short
git diff --stat
git diff
git diff --check
python tools/check_legacy_namespace.py
```

The namespace check compares the `siestaflow.*` inventory in `src/qraft` by
file, identifier and count. It is an additional guard against accidental
renaming, not a complete verifier for persisted formats or hashes. Changes to
its baseline need substantive review rather than automatic regeneration.

Obtain independent review of the diff and validation results. Confirm that
the configured Git identity belongs to the actual contributor. Follow the
governance authorization rules for commits, pushes, tags and remote jobs.

## Validate the candidate

Run the repository's existing gates in the prepared development environment:

```bash
git diff --check
python tools/check_legacy_namespace.py
python -m compileall -q src
python -m pytest -q
```

Check relative documentation links and example paths. Packaging changes also
require a clean wheel and sdist build with `python -m build` and inspection of
the resulting distributions.

The existing [Linux CI workflow](../../.github/workflows/ci.yml) runs regression
tests, including clean installation and recovery, on Python 3.11, 3.12 and
3.13, checks dependencies and builds wheel/sdist distributions. Reuse that
coverage and record the actual candidate commit and CI result. A workflow
definition or an older passing run does not establish that the new candidate
passed. Linux CI does not establish acceptance on a particular HPC system;
record missing external evidence as such.

After integration, verify the merged commit and its CI result. Installation
claims should refer to the tested source or distribution and environment.

The distribution metadata must identify `qraft-hpc`; built wheel filenames use
`qraft_hpc`. Verify `import qraft`, the `qraft` command and installed version
metadata in a fresh environment. Do not install the unrelated `qraft` PyPI
distribution alongside this package. Updating metadata does not establish
PyPI availability or publish a release.

## Prepare a release separately

Do not increment the version solely for this documentation preparation.
When a release is approved, synchronize its version, changelog and metadata;
build from a clean, identified commit and retain the validation record.
Create a new release tag for that commit. Never move or overwrite an existing
published tag to make it refer to newer work. For example, a published
`v0.2.0` must remain attached to its original commit; a subsequent release
needs an independently selected, unused version.

A GitHub repository rename is a separate publication action. Confirm the
destination, then update repository URLs, clone instructions and integrations
together. Preserve the distribution name `qraft-hpc`, import and CLI name
`qraft`, legacy namespaces and historical evidence. Verify links after the rename.

## Prepare JOSS material from verified facts

Before submission, review the current official
[submission guidance](https://joss.readthedocs.io/en/latest/submitting.html)
and [review criteria](https://joss.readthedocs.io/en/latest/review_criteria.html).
This document does not certify compliance with those evolving requirements.

Collect and confirm authorship and affiliations, citation metadata, the
research problem, comparison with related software, actual research use and
supporting evidence. Record development and release history accurately.
Prepare `paper.md`, its references and `CITATION.cff` from confirmed information;
do not infer authorship from commit activity or invent scientific impact.
Distinguish unavailable evidence from a failed check, and keep a paper draft
clearly identified until the authors approve its factual content.

Document automation or AI assistance as required by the applicable publication
policy and actual contribution history. Repository hygiene, software tests
and the paper's scientific claims each need their own supporting evidence.
