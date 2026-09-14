# ADR-0002 — Capacidades y recetas para authoring científico extensible

Estado: `Accepted`
Fecha: 2026-08-01

## Contexto

El compilador, `run prepare` y el ejecutor remoto ya forman una trayectoria
canónica. Sin embargo, las herramientas científicas y varias superficies CLI
se incorporaron como cortes aislados. Añadir directamente comandos para malla,
k-grid, relajación, DOS, PDOS, bandas, fonones y óptica produciría lógica
duplicada y acoplaría la interfaz a cada cálculo.

## Decisión

La intención del usuario se resuelve mediante dos extensiones explícitas:

- un `WORKFLOW_BUILDER` construye tareas canónicas para una capacidad;
- una `RECIPE` compone capacidades y produce un `WorkflowDefinition` ordinario.

Ambas se registran mediante `CapabilityRegistry`; importar módulos no modifica
estado global. Una `WorkflowAuthoringService` es la API compartida por CLI y
futuras interfaces. La salida siempre continúa por:

```text
ScientificIntent → Recipe → WorkflowDefinition → workflow.lock.json
→ run prepare → run.lock.json → paquete → Evidence / Results
```

Los accesos especializados de CLI serán fachadas sobre la misma API. No pueden
implementar renderers, selectores, ejecución o aceptación científica propios.
Cuando una capacidad requiere una adaptación de runtime nueva, `RunPreparer`
la recibe mediante su registro explícito de adaptadores de tarea; el bucle de
preparación no añade una rama especial por cada módulo científico.

## Primer corte

`siestaflow.recipe.siesta.mesh-evidence-evaluation` consume una regla y
observaciones estructuradas, crea un nodo `validation`, compila y se prepara
como gate autocontenido. El paquete ejecuta el mismo evaluador general de
convergencia y produce `mesh-convergence-report.json`.

Este corte se clasifica `EVIDENCE_EVALUATION_ONLY`: no ejecuta SIESTA ni genera
energías o fuerzas. El futuro productor SIESTA debe declarar esos artefactos y
conectarlos al mismo evaluador por aristas del DAG.

## Consecuencias

- Nuevos módulos se añaden registrando capacidades y recetas, no modificando el
  compilador o creando rutas de ejecución.
- El registro se valida con Mesh, después con k-grid y finalmente con una
  capacidad consumidora como DOS o bandas antes de declararlo general.
- Los archivos destinados al runtime remoto son JSON portable y hash-bound.
- `READY_FOR_HUMAN_REVIEW` continúa sin autorizar propagación científica.
- Las rutas de campaña históricas permanecen como compatibilidad y no reciben
  nuevas semánticas científicas.

## Alternativas rechazadas

- Un subcomando con lógica propia por cálculo: duplica contratos y ejecución.
- Una jerarquía universal diseñada de antemano para toda SIESTA: abstrae sin
  evidencia y eleva el costo de migración.
- Reescribir compilador y ejecutor: descarta componentes ya verificados sin
  resolver el problema de authoring.
