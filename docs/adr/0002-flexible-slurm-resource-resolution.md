# ADR-0002 — Resolución flexible y confirmada de recursos Slurm

Estado: `Superseded`
Fecha: `2026-08-01`

Reemplazado operativamente para nuevas ejecuciones por
[ADR-0004 — Contrato live Slurm a DerivedPlacement](0004-live-slurm-placement-contract.md).
Los snapshots descritos aquí siguen siendo evidencia reproducible, pero no son
autoridad para el estado actual ni para nuevas selecciones.

## Contexto

`workflow.lock.json` es un contrato científico determinista y no puede incluir
datos administrativos ni disponibilidad mutable del scheduler. La preparación
canónica ya converge en `run prepare`, `run.lock.json` y un paquete
autocontenido, pero los perfiles resueltos podían quedar ligados a una
partición concreta.

## Problema

La capacidad Slurm cambia y una selección automática no demuestra autorización
administrativa ni estima el tiempo de cola. Se necesita observar, comparar y
persistir una elección sin introducir una segunda ruta de empaquetado.

## Alternativas consideradas

- Mantener perfiles permanentes por partición: duplica configuración mutable y
  exige edición manual ante cambios del scheduler.
- Aceptar sólo overrides manuales: conserva control humano pero no ofrece
  evidencia comparable ni ranking explicable.
- Elegir automáticamente el primer candidato: es opaco y convertiría una
  observación dinámica en autorización implícita.
- Resolver desde un snapshot versionado, exigir confirmación humana y entregar
  el perfil resuelto al preparador canónico: opción adoptada.

## Decisión

Se añade una capa local y de sólo lectura:

```text
discovery/import → capability snapshot → candidates → human confirmation
→ resolved execution profile → run prepare → run.lock/package
```

El snapshot Slurm `1.0` registra fuentes y valores desconocidos. El resolvedor
puro clasifica variantes sin nombres de cluster incorporados al núcleo. La ruta
por candidato y los overrides manuales requieren `--confirm`; el perfil ya
resuelto conserva la compatibilidad histórica. La resolución se persiste en
`PreparedRun.metadata.execution_resolution`, por lo que el envelope
`siestaflow.run-lock@1.0` y los lectores existentes siguen siendo válidos.

## Consecuencias

Los paquetes flexibles incorporan `cluster-snapshot.json` y
`execution-resolution.json`. El preparador y el verificador comprueban que la
elección, el perfil, la campaña y `submit.slurm` coinciden. El ranking sólo
ordena ajuste estructural y capacidad observada: no predice espera ni envía
trabajos. `sjstat -c` sigue siendo un parser/importador opcional.

## No objetivos

No se implementan predicción de cola, aprendizaje automático, monitor continuo,
daemon, autoenvío, modificación de jobs, PBS/LSF, GUI, Parsl ni decisiones
científicas automáticas.

## Compatibilidad

Los `run.lock.json` anteriores no contienen el nuevo metadato y se aceptan. Un
perfil resuelto existente sigue usando `run prepare` sin `--confirm`. Ningún
campo de `workflow.lock.json` cambia; FDF, pseudopotenciales, geometría, DAG y
parámetros científicos quedan fuera de esta decisión.

## Migración

No hay migración obligatoria: los paquetes nuevos pueden optar por snapshot o
por selección manual confirmada. Los perfiles históricos se conservan como
entrada compatible y no se reescriben. Los paquetes con resolución flexible
fallan cerrados si la confirmación o la coherencia con el submit no son válidas.

## Evidencia

- `tests/runs/test_slurm_resources.py` cubre snapshot, variantes, cero nodos
  libres, rechazos, confirmación y dos paquetes del mismo workflow.
- `tests/runs/test_prepared_run.py` conserva la ruta de perfil resuelto.
- El paquete de Fase 3 debe superar verificación local y `sbatch --test-only`
  en Yoltla antes de cualquier envío manual.

## Referencias

- [Backbone](../design/QRAFT_BACKBONE.md)
- [Gobernanza](../developer/DEVELOPMENT_GOVERNANCE.md)
- [Aceptación Fase 3](../validation/PHASE3_PREPARED_RUN_ACCEPTANCE.md)
- [ADR-0001](0001-single-codebase-canonical-execution-path.md)
