# ADR-0001 — Una base de código y una ruta canónica de ejecución

Estado: `Accepted`
Fecha: 2026-08-01

## Contexto

El repositorio contiene Core Contracts, un compilador de workflows,
`workflow.lock.json`, `run prepare`, `run.lock.json`, un constructor de paquete
autocontenido y `AllocationController`. También conserva superficies anteriores
de campaign, preview, controller-package, smokes y evidencia remota histórica.
Estas superficies nacieron como cortes verticales y no todas derivan todavía de
la misma representación bloqueada.

## Problema

Dos rutas de producción que evolucionen por separado pueden validar recursos,
transferir artefactos, persistir estado o declarar éxito con reglas distintas.
Separar una edición local y otra HPC como bases de código divergentes agravaría
el riesgo y rompería la trazabilidad de commit a resultado.

## Alternativas consideradas

- Mantener campaign y workflow/run como rutas de producción equivalentes. Se
  rechaza porque duplica semántica crítica y aceptación.
- Crear una edición ligera independiente para HPC. Se rechaza porque produce
  forks y correcciones no uniformes.
- Sustituir el runtime por un framework genérico. Se rechaza porque cambia el
  alcance fundacional y no elimina la necesidad de contratos SIESTAFLOW.
- Adoptar workflow lock → run prepare como ruta canónica y conservar adaptadores
  explícitos para compatibilidad. Es la opción elegida.

## Decisión

SIESTAFLOW mantiene una sola base de código y esta trayectoria de producción:

```text
Project → WorkflowDefinition → workflow.lock.json → run.lock.json
→ paquete autocontenido → AllocationController → Evidence / Results
```

`workflow compile` es la autoridad de la representación bloqueada y
`run prepare` el único puente que puede producir el paquete usado para cerrar
la Fase 3. Editable, wheel/sdist y paquete HPC son distribuciones del mismo
repositorio.

## Consecuencias

- La aceptación remota previa de un packager distinto no cierra la ruta
  canónica.
- Las rutas históricas permanecen disponibles mientras exista necesidad de
  compatibilidad o evidencia, pero no reciben semántica crítica independiente.
- La integración Project → WorkflowDefinition y algunos tipos de tareas siguen
  pendientes; fallan cerrado en lugar de saltarse el lock.
- Los cambios futuros de esta trayectoria requieren otro ADR.

## Compatibilidad

`remote controller-package` conserva campañas schema 1/2 como
`COMPATIBILITY`. `campaign worker/progress/watch` puede seguir operando como
runtime u observación compartidos. Simulaciones, previews y smokes no adquieren
autoridad de producción. No se elimina ni reescribe evidencia histórica.

## Migración

1. Documentar la clasificación vigente en el roadmap.
2. Reutilizar contratos canónicos desde rutas de compatibilidad o añadir
   adaptadores explícitos.
3. Impedir nuevas diferencias de validación, transferencia, persistencia,
   recuperación y éxito.
4. Marcar una CLI como deprecated sólo después de disponer de reemplazo,
   pruebas de compatibilidad y ventana de retiro documentada.

## Evidencia

- `src/siestaflow/workflows/compiler.py`
- `src/siestaflow/run_preparation.py`
- `src/siestaflow/contracts/run.py`
- `src/siestaflow/controller_package.py`
- `src/siestaflow/execution/allocation_controller.py`
- `tests/workflows/`, `tests/runs/` y `tests/m4/`
- `docs/validation/PHASE3_PREPARED_RUN_ACCEPTANCE.md`

La evidencia remota canónica sigue pendiente: no hay locks de un paquete
generado por `run prepare` dentro de la evidencia remota versionada.

## Referencias

- [`SIESTAFLOW_BACKBONE.md`](../design/SIESTAFLOW_BACKBONE.md)
- [`SIESTAFLOW_PRODUCT_ROADMAP.md`](../design/SIESTAFLOW_PRODUCT_ROADMAP.md)
- [`DEVELOPMENT_GOVERNANCE.md`](../developer/DEVELOPMENT_GOVERNANCE.md)
