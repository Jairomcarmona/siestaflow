# Evidencia local — segunda validación de extensibilidad k-grid

Fecha: 2026-08-01

Estado: `LOCAL_TWO_AXIS_AUTHORING_VALIDATED`

## Resultado

La receta `siestaflow.recipe.siesta.kgrid-evidence-evaluation` se registró sin
modificar la CLI, el compilador ni el bucle de preparación de campañas. La CLI
existente la muestra mediante `workflow recipes`; `workflow create`,
`validate`, `plan`, `compile` y `run prepare` operan sin un camino especial.

La regla k-grid es independiente de la de Mesh: acepta solamente una serie
Monkhorst-Pack de refinamiento estricto con shifts constantes, compara energía
por átomo y fuerzas vectoriales contra la referencia, y valida SCF, firma
magnética, identidad científica, grilla usada y estabilidad consecutiva. Su
DAG solo puede solicitar niveles de extensión declarados.

El fixture preparado terminó en `READY_FOR_HUMAN_REVIEW`; no hubo ejecución
SIESTA, Slurm remoto, SSH ni aceptación científica automática.

## Pruebas focalizadas

```text
python -m pytest -q tests/unit/test_scientific_kgrid.py tests/authoring/test_workflow_authoring.py tests/runs/test_adaptive_prepared_run.py
29 passed
```

```text
python -m pytest -q
416 passed

python -m compileall -q src
PASS

git diff --check
PASS
```
