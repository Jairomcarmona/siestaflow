# Public CLI

## Stable in 0.2

```text
qraft --version        installed package version
qraft --help           command discovery
qraft                  same task-oriented command discovery
qraft init [PATH]      create an editable campaign file
qraft check TARGET     evaluate readiness without execution
qraft run TARGET       run a checked campaign or calculation
qraft status [TARGET]  show progress and the next available action
qraft resume [FDF]     continue using saved recovery state
qraft results [TARGET] inventory recorded outputs and route supported exports
qraft examples [TOPIC] show fixture-backed learning topics
```

For environment and execution-plan inspection, use `qraft setup --help` and
`qraft inspect --help`. Architecture families are available through
`qraft advanced --help`.

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
