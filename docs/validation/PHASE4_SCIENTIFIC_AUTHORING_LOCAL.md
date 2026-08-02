# Evidencia local — authoring científico modular de Fase 4

Fecha: 2026-08-01

Estado: `LOCAL_AUTHORING_VERTICAL_SLICE`

## Recorrido comprobado

```text
ScientificIntent JSON
→ RECIPE registrada
→ WORKFLOW_BUILDER registrado
→ WorkflowDefinition
→ workflow.lock.json
→ run prepare
→ run.lock.json y paquete autocontenido
→ AllocationController local
→ mesh-convergence-report.json
```

El reporte del fixture estructurado terminó en `READY_FOR_HUMAN_REVIEW`. Este
estado no propagó parámetros ni produjo aceptación científica automática.
El reporte conserva `rule_id`, SHA-256 de la regla y la lista ordenada de
observaciones con identificador y SHA-256.

La CLI usa `WorkflowAuthoringService` para listar, describir y materializar
recetas; posteriormente reutiliza `workflow validate/plan/compile` y
`run prepare`. El preparador resuelve el nuevo runtime mediante un registro de
adaptadores de tarea, sin una condición Mesh dentro de su bucle central.

## Verificaciones

```text
python -m pytest -q tests/authoring/test_workflow_authoring.py tests/contracts/test_plugin_registry.py tests/contracts/test_versioning_and_serialization.py tests/unit/test_scientific_convergence.py tests/runs/test_adaptive_prepared_run.py tests/workflows/test_workflow_compiler.py
48 passed

python -m pytest -q
403 passed

python -m compileall -q src
PASS

git diff --check
PASS
```

Las pruebas incluyen registro explícito y congelado, contratos de entrada y
salida, recipe desconocida, rutas inseguras, JSON no portable, no overwrite,
dry-run sin escrituras, compilación determinista, hashes de artefactos,
preparación autocontenida, verificador del paquete y ejecución local del gate.

## Límites

- La receta implementada evalúa evidencia; no ejecuta SIESTA.
- No existe todavía un productor canónico de observaciones de energía, fuerzas,
  malla real y firma magnética desde salida SIESTA.
- K-grid debe validar la reutilización del estudio paramétrico antes de declarar
  estable esa abstracción.
- DOS o bandas deben validar una capacidad consumidora antes de afirmar
  extensibilidad general para propiedades electrónicas.
- No se ejecutó Slurm, SSH ni trabajo remoto; Fase 4 permanece abierta.
