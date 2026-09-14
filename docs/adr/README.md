# Architecture Decision Records

Los ADR registran decisiones arquitectónicas con consecuencias duraderas. Se
numeran en orden (`0001-...md`), se basan en
[`ADR_TEMPLATE.md`](ADR_TEMPLATE.md) y usan uno de estos estados:

```text
Proposed | Accepted | Superseded | Rejected
```

Un ADR aceptado no se reescribe para ocultar una decisión posterior. La nueva
decisión crea otro ADR y el anterior pasa a `Superseded` con una referencia.
Correcciones tipográficas que no cambien el sentido sí son admisibles.

Se requiere ADR para cambios de ruta canónica, contratos, locks, persistencia,
reanudación, plugins, artefactos, perfiles incompatibles, backends, bases de
datos o servicios externos. El autor adjunta evidencia reproducible y describe
compatibilidad y migración antes de solicitar aceptación humana.

## Índice

- [ADR-0001 — Una base de código y una ruta canónica de ejecución](0001-single-codebase-canonical-execution-path.md)
- [ADR-0002 — Resolución flexible y confirmada de recursos Slurm — Superseded por ADR-0004](0002-flexible-slurm-resource-resolution.md)
- [ADR-0004 — Contrato live Slurm a DerivedPlacement](0004-live-slurm-placement-contract.md)
