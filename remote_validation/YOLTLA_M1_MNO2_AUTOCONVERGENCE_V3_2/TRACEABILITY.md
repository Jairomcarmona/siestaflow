# Trazabilidad V3.2

Cada cálculo vive en:

`runs/autoconvergence/calculations/<stage>/<task>/attempts/attempt-NNNN/`

Un intento conserva `input.fdf`, PSML, `lineage.json`, `command.json`,
`environment.json`, `siesta.out`, `siesta.err`, `mn_moments.csv`,
`result.json` y `artifacts_manifest.json`.

`result.json` incluye energía, fuerzas completas, fuerza máxima/RMS, tabla
Mulliken, clasificación magnética, warnings clasificados, clase de fallo,
hashes y tiempo. Los intentos nunca se sobrescriben.

Etapas:

1. `00_scaling`: equivalencia y rendimiento 64/128 MPI.
2. `01_mesh`: Mesh frente a todos los niveles superiores.
3. `02_kgrid`: k-grid frente a todos los niveles superiores.
4. `03_basis`: DZP/TZP con energía y fuerzas.
5. `04_closure`: cierre Mesh-k-base.
6. `05_u_spin`: matriz U/estado y clasificación final.
7. `06_u_transfer`: transferencia DFT+U y promoción opcional.

Cada etapa produce `summary.csv` y `decision.json`. El nivel global conserva
`events.jsonl`, `traceability.csv`, `final_summary.json`, preflight y decisiones.
