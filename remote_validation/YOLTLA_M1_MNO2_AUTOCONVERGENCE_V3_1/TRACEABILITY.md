# Esquema de trazabilidad

```text
runs/autoconvergence/
|-- preflight/
|-- calculations/
|   |-- 01_mesh/
|   |-- 02_kgrid/
|   |-- 03_basis/
|   `-- 04_u_spin/
|       `-- <task_id>/
|           |-- status.json
|           |-- reuse.json                 # solo si reutiliza referencia
|           `-- attempts/
|               `-- attempt-NNNN/
|                   |-- input.fdf
|                   |-- Mn.psml
|                   |-- O.psml
|                   |-- lineage.json
|                   |-- command.json
|                   |-- environment.json
|                   |-- siesta.out
|                   |-- siesta.err
|                   |-- result.json
|                   `-- artifacts_manifest.json
|-- stages/
|   `-- <stage>/
|       |-- summary.csv
|       `-- decision.json
|-- events.jsonl
|-- traceability.csv
`-- final_summary.json
```

`lineage.json` registra parámetros, FDF base, pseudopotenciales, cálculo padre,
decisión padre, trabajo Slurm y distribución 2x64. `artifacts_manifest.json`
registra tamaño y SHA-256 de cada archivo del intento.

Una reanudación crea `attempt-NNNN` nuevo. Solo se reutiliza un resultado
anterior cuando el estado es `PASS` y el SHA-256 del FDF coincide exactamente.
