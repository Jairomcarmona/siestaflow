# Internal compatibility shell

The legacy shell remains in the source for compatibility testing, but it has
no public CLI entry point. Running `qraft` with no arguments now prints the V2
task orientation and exits. The historical command language retained
internally is:

```text
qraft> env
qraft> config
qraft> profile list
qraft> profile local
qraft> fdf calc.fdf
qraft> validate
qraft> plan
qraft> run
qraft> status
qraft> resume
qraft> paths
qraft> attempts
qraft> errors
qraft> exit
```

CLI and REPL call the same `QraftApplication`; they do not maintain separate
planning or execution logic. `set`, `unset`, `reset`, `show resolved`, `np`,
`nodes`, `partition`, `launcher`, and `walltime` manage session overrides.
Errors leave the shell usable. History is session-local in v1.
