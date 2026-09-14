# Windows Atomic I/O Classification

The prior 500-candidate recovery evidence recorded native Windows
`PermissionError [WinError 5]` while replacing the canonical state file. That
evidence remains preserved in `../RECOVERY_ENVIRONMENT_BLOCK.md`.

This M9-R1 matrix performed one new minimal P=4 persistence/concurrency
experiment through N=25 and N=100. It observed zero atomic write failures and
zero `WinError 5` values. The evidence therefore supports the exact
classification:

`NOT_REPRODUCED_CAUSE_UNRESOLVED`

It does not support a claim that QRAFT has a same-process state-file race:

- runtime state/event calls share a reentrant lock;
- `atomic_write_json` creates a unique sibling temporary file;
- state replacement uses `os.replace`;
- no retry is implemented; and
- this matrix measured one concurrent state write at most.

Nor does it identify an external actor conclusively. Windows access denial can
be influenced by sandboxing, indexing, antivirus, or another open handle, but
none is asserted here without a reproducible trace.

No retry, backoff, error suppression, test relaxation, or product change was
introduced. A future fix must first define the intended durable-state semantics
and validate recovery under a persistent native Windows workspace.
