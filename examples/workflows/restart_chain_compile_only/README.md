# Restart-chain workflow example

This example exercises Phase 1 only: schema validation, artifact resolution,
topological planning, graph rendering, and deterministic lock compilation.

The FDF files are intentionally incomplete and are **not authorized for
scientific execution**.

```bash
siestaflow workflow validate workflow.json
siestaflow workflow plan workflow.json
siestaflow workflow graph workflow.json --format mermaid
siestaflow workflow compile workflow.json --output workflow.lock.json
```
