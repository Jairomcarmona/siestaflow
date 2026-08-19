# Recovery

`qraft resume` reloads the saved session configuration and executes normal
planning/validation again. A completed, hash-consistent, technically valid
attempt is reused and not repeated. A missing, failed, incomplete or tampered
attempt causes a new immutable attempt.

Contract:

```text
at-least-once execution
immutable attempts
idempotent recovery of valid work
```

QRAFT does not promise exactly-once process launch. An allocation loss may
interrupt an attempt; after scheduler evidence says the old allocation is
terminal, start a new allocation and resume. Never edit an existing
`attempt.json`. `session.json` is mutable convenience configuration, not the
scientific evidence authority.
