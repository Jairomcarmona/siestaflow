# Matriz de migración de pruebas

## Ejecuciones de M0

| Suite | Entorno | Resultado | Clasificación |
|---|---|---|---|
| Donante completo | copia temporal, `PYTHONPATH=<copia>/src`, sin bytecode | 272 passed en 2.26 s | OBSERVED |
| Smoke donor | misma copia temporal | 16/16 checks, 0.030 s | OBSERVED |
| Caracterización M0 | `siestaflow/tests/characterization` | 11 passed en 0.43 s | OBSERVED |
| Primera suite accidental sobre extracción | `context/donor`, luego restaurado | 272 passed; sólo creó cachés, 642/642 hashes originales intactos | OBSERVED, no es ejecución válida de aislamiento |
| Primera repetición temporal sin `PYTHONPATH` | copia temporal | 272 passed, pero importó un checkout externo instalado | CONTRADICTORY/INVALID_AS_EVIDENCE |

No se ejecutaron `sbatch`, `srun`, `squeue`, `sacct`, `scontrol`, MPI, SIESTA ni SSH.

## Migración por familia

| Familia donante | Cobertura observada | Decisión | Prueba objetivo SIESTAFLOW |
|---|---|---|---|
| `test_slurm.py` | headers, orden, comandos, sbatch ausente | REFACTOR | renderer puro + snapshots por launcher/perfil |
| `tests/fake_slurm.py` | patch global de `check_output`, PD/R/CD | REFACTOR | fake inyectado con submit/query/accounting explícitos |
| `test_utils.py` | rutas, metadata, estado, outputs | REFACTOR | confinamiento, atomicidad, artefactos y estados tipados |
| pruebas Project/Workspace | centinela, nombres, import | PORT escenarios | crash/collision/symlink/no-overwrite |
| `test_convergence_controller.py` | loops con mocks y dry-run | REWRITE | worker dentro de una asignación + gates/checkpoints |
| `test_regression_guards.py` | Ecut/U/SLURM | DISCARD física QE; REFACTOR patrón | mesh SIESTA sólo cuando M5 lo autorice |
| `test_golden_regression.py` | dos outputs QE reales | DISCARD fixtures; PORT patrón | outputs SIESTA versionados futuros, sin inventarlos en M0 |
| `test_debug_infra.py` | logger y monkey-patch | REFACTOR | fake filesystem/dependencies sin patch global |
| `test_v180_auditor.py` | regex de errores QE/SLURM | REWRITE | catálogo de fallos SIESTA/SLURM con unknown→REVIEW |
| `scripts/smoke_test.py` | sandbox harvester/janitor/logger | REFACTOR | smoke genérico sin proclamar aptitud remota |
| `test_validator.py`/QE inputs | sintaxis QE | DISCARD | FDF validator futuro contra manual oficial |
| pseudo tests UPF | UPF NC/PAW | DISCARD | PSML/PSF auditor futuro |

## Pruebas de caracterización creadas

| Archivo | Comportamientos fijados |
|---|---|
| `test_slurm_contract.py` | un script con pasos secuenciales, headers, fail-fast; ausencia worker/time/gate; deduplicación |
| `test_workspace_contract.py` | staging/versiones/mapa, preservación de fuente, escape `../`, overwrite `_copy_dir` |
| `test_persistence_contract.py` | status/historial/atomicidad, checksum ignorado, dry-run con escritura, wrapper roto |
| `test_fake_slurm_contract.py` | monkey-patch global absorbe comandos ajenos |

## Riesgos de falsos positivos

- El paquete `src/` no queda automáticamente primero en imports; una instalación editable externa puede contaminar pytest. Toda CI futura debe instalar el checkout en un venv limpio y verificar `module.__file__`.
- Muchos tests validan strings/retornos pero no side effects, provenance o ausencia de sobrescritura.
- Mocks de métodos privados pueden permitir que integraciones con firmas rotas pasen.
- Dry-run genera datos sintéticos y puede ocultar que se escribieron archivos.
- `FakeSlurmEnvironment` parchea globalmente `subprocess.check_output` y devuelve vacío para comandos desconocidos.

## Pruebas no ejecutadas

- Coverage: no necesaria para el contrato M0 y podría mezclar imports/cachés; `DOCUMENTED_ONLY`.
- Flujos reales de submit/polling/restart: prohibidos localmente y requieren clúster; `MISSING`.
- SIESTA/parser FDF/pseudopotenciales: fuera de M0; `NOT_STARTED`.
- Tests del snapshot científico: no necesarios para caracterizar QEF y no deben reinterpretarse como outputs SIESTA.

