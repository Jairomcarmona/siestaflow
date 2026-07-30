# Evidencia de pruebas M1

## Suites

| Área | Evidencia automatizada |
|---|---|
| Dominio/imports | provenance exacta del checkout |
| Paths | traversal POSIX/Windows, absolutos, drive, controles y separadores |
| Filesystem | zero-side-effects dry-run e impedir overwrite |
| Persistencia | atomic roundtrip, sin temp, corrupción, append/replay/conflicto |
| Autorización | authorized, unauthorized, stale y hash mismatch |
| Gates | PASS/REVIEW/FAIL/BLOCKED no booleanos |
| Launcher fake | siete modos requeridos |
| Fake SLURM | seis estados, time/signal/end y cola vacía sin evidencia |
| TimeBudget | fórmula, frontera estricta y UNKNOWN_RUNTIME |
| Fallos | once tipos requeridos |
| Campaña | éxito, review, fail, poco tiempo, interrupción/resume, auth parcial, warning |
| Recuperación | RUNNING→INTERRUPTED→nuevo intento |
| Idempotencia | completed no se repite |
| Smoke | proyecto→tres tareas→state/events/artifacts |
| Regresión M0 | cuatro archivos de caracterización donor |

## Criterios de aceptación cubiertos

`PROMPT_SELF_PERSISTED`, `PATH_TRAVERSAL_BLOCKED`, `IMPORT_PROVENANCE_VERIFIED`, `DRY_RUN_ZERO_SIDE_EFFECTS`, `ATOMIC_STATE_WRITE_PASS`, `APPEND_ONLY_EVENTS_PASS`, `AUTHORIZATION_ENFORCED`, `REVIEW_STOPS_CAMPAIGN`, `EMPTY_SQUEUE_NOT_SUCCESS`, `FAKE_SLURM_PASS`, `TIME_BUDGET_PASS`, `INTERRUPTION_RESUME_PASS`, `NO_DUPLICATE_COMPLETED_TASKS`, `SIMULATED_ONE_ALLOCATION_THREE_TASKS_PASS` y `NO_SIESTA_IMPLEMENTATION_PRESENT` se verifican localmente en el cierre.

## Ejecución final observada

| Suite | Resultado |
|---|---|
| Unitarias M1 | 52 passed en 0.25 s |
| Integración M1 | 10 passed en 0.99 s |
| Smoke M1 | 1 passed en 0.17 s |
| Caracterización M0 | 11 passed en 0.40 s |
| Ejecución conjunta final | 74 passed en 1.68 s |

Los tiempos son observaciones locales del 2026-07-20 y no se confunden con validación remota.
