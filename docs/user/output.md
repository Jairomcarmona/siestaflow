# Output and evidence

Authority is explicit:

```text
Event / State / Evidence = authoritative machine record
qraft.out                 = human-readable campaign view
CSV                       = derived tabular view
```

`qraft.out` schema 1.1 records execution sessions, resolved command/resources,
scientific and execution identities, DAG node start/results, paths, compact
diagnostics and recovery. It may contain several sessions after resume.

Each immutable attempt preserves `attempt.json`, `stdout.txt`, `stderr.txt`,
staged inputs and artifact hashes. CSV is written only when a contributor
provides tabular values and must remain derivable from authoritative evidence.
Use `qraft> paths`, `qraft> attempts`, `qraft> errors`, or `qraft status` to
locate records.

Unknown persistent schema versions fail explicitly. QRAFT never silently
migrates scientific evidence.
