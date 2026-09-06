# Public CLI

## Stable in 0.2

```text
qraft --version        installed package version
qraft --help           command discovery
qraft                  same task-oriented command discovery
qraft init [PATH]      create an editable campaign file
qraft check TARGET     classify a target (readiness arrives in Phase 5)
qraft setup env         inspect external capabilities
qraft setup config      show effective configuration/provenance
qraft setup profile ... list/show/validate execution profiles
qraft check TARGET      evaluate readiness without execution
qraft inspect plan FDF  resolve ScientificIdentity, ExecutionSpec and DAG
qraft run FDF          preflight and execute single_fdf
qraft status           read single_fdf state
qraft resume           recover the saved single_fdf session
```

Use `COMMAND --help` for all options. Paths may be absolute or relative and
paths with spaces are supported. CLI overrides have the highest precedence and
change execution identity, not scientific identity.

Exit behavior:

```text
0 success or read-only inspection completed
2 invalid input/configuration or preflight block
3 an attempted execution failed technical validation
4 reserved for explicit human review/block policy
5 reserved for an unexpected internal QRAFT failure
```

Normal user errors are concise and omit tracebacks. Existing workflow,
scientific, examples, remote and prepared-package command families are
experimental or specialized unless their own acceptance document says
otherwise.
