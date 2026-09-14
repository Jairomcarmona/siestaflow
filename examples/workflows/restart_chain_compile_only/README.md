# Restart-chain workflow example

This example exercises Phase 1 only: schema validation, artifact resolution,
topological planning, graph rendering, and deterministic lock compilation.

The FDF files are intentionally incomplete and are **not authorized for
scientific execution**.

```bash
qraft workflow validate workflow.json
qraft workflow plan workflow.json
qraft workflow graph workflow.json --format mermaid
qraft workflow compile workflow.json --output workflow.lock.json
```
