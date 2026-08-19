# Interactive shell

Run `qraft` with no arguments:

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
