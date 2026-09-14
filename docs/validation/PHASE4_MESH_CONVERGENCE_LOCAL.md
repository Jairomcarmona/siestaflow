# Evidencia local — regla de convergencia de malla de Fase 4.2

Fecha: 2026-08-01

Estado: `LOCAL_SCIENTIFIC_RULE_CONTRACT`

## Resultado

Se implementó un evaluador general y fail-closed para evidencia de convergencia
de malla. Los valores científicos no están codificados en el núcleo: el perfil
M1 vive en `expected_contracts/m1_mesh_convergence_rule.yaml` y conserva
`synthetic_only` en la campaña.

El DAG lógico inicial materializa una tarea por cutoff y un fan-in de evaluación.
La evaluación solo puede solicitar una confirmación eggbox declarada, la serie
de extensión declarada o detenerse para revisión humana. `READY_FOR_HUMAN_REVIEW`
no equivale a aceptación científica ni autoriza la propagación del parámetro.

No se modificaron FDF, geometrías, pseudopotenciales, carga, spin, funcional,
basis o entradas del snapshot científico. No se ejecutaron SIESTA, Slurm, SSH
ni trabajos remotos.

## Verificaciones

```text
python -m pytest -q tests/unit/test_scientific_convergence.py tests/m2/test_outputs_campaigns.py tests/generalization/test_project_packages_end_to_end.py
37 passed

python -m pytest -q
397 passed

python -m compileall -q src
PASS

git diff --check
PASS
```

Las pruebas cubren contrato y unidades, orden estricto del barrido, fan-out y
fan-in, normalización energética por átomo, diferencias vectoriales de fuerza,
estabilidad consecutiva, mallas reales distintas, SCF, firma magnética,
confirmación eggbox, extensión acotada, identidad científica/hash, evidencia
huérfana o duplicada, determinismo y ausencia de aceptación automática.

## Límite pendiente

Este corte define la regla y su expansión lógica. Aún falta adaptar sus nodos
científicos al WorkflowDefinition canónico, compilar `workflow.lock.json`,
prepararlos mediante `run prepare` y obtener evidencia con SIESTA real. La Fase
4 permanece abierta.
