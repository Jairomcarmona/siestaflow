# Contrato conductual SLURM

## Evidencia del donante

| Conducta | Estado | Evidencia |
|---|---|---|
| Render puro devuelve texto | OBSERVED | `slurm.generate_slurm_script`; prueba `test_slurm_contract.py` |
| Orden canónico y fail-fast por paso | OBSERVED | `validate_steps`, `_build_step_block` |
| Un script puede contener varios ejecutables secuenciales | OBSERVED | NSCF → DOS en caracterización |
| Job ID desde `sbatch` | OBSERVED en tests/mocks; no remoto | `submit_slurm`, controller |
| Polling y estados terminales | OBSERVED en código/tests simulados | `squeue`; Fake SLURM |
| Recursos reales para SIESTA/Yoltla | MISSING | auditoría DFT |
| Asignación persistente SIESTA | MISSING | controller usa un sbatch por punto |

## Contrato que se conserva

El futuro `SLURM_SCRIPT_RENDERER` debe ser puro y determinista: recibe un perfil validado, una orden de worker y rutas relativas; produce texto sin escribir ni someter. Debe renderizar job name, partition opcional, nodes, ntasks, tareas por nodo opcionales, memoria opcional, walltime, stdout/stderr con job id, signal previo al timeout, entorno explícito y comando del worker.

La ejecución debe ser fail-closed: una configuración incompleta, recurso contradictorio, path no confinado o launcher no autorizado impide renderizar. Ningún default QEF/Yoltla (`qz2d-64p`, 20 cores, QE 7.3, `mpiexec.hydra`) se traslada.

## Separación obligatoria

| Responsabilidad | Componente futuro |
|---|---|
| Texto `#SBATCH` | `SLURM_SCRIPT_RENDERER` |
| Invocación de una tarea | `PROCESS_LAUNCHER` |
| Un sbatch, cola secuencial autorizada | `PERSISTENT_ALLOCATION_WORKER` |
| Tiempo restante/margen de salida | `TIME_BUDGET` |
| Estado SLURM y exit codes | `FAILURE_CLASSIFIER` + evidencia |
| Continuar/detener/revisar | `GATE_ENGINE` + `AUTHORIZATION_ENGINE` |

`PROCESS_LAUNCHER` debe aceptar implementaciones `LocalFakeLauncher`, `SrunLauncher`, `MpiexecHydraLauncher`, `MpirunLauncher` y `CustomCommandLauncher`. El renderer nunca agregará `-np`, redirecciones ni argumentos específicos por detrás del launcher.

## Semántica `ONE_SBATCH_MANY_SIESTA_RUNS`

Dentro de una única asignación, el worker carga un plan ya autorizado, reconcilia el checkpoint, evalúa `TIME_BUDGET`, lanza exactamente una tarea, captura stdout/stderr/exit/timing, registra artefactos, analiza, evalúa gate, persiste atómicamente y sólo entonces considera la siguiente tarea. Una tarea `REVIEW`, `FAIL` o `BLOCKED` detiene el worker. El sanity `M1_U0_FM` no usa este contrato: es un job independiente y termina para revisión humana.

## Salidas y evidencia

- stdout/stderr por asignación y por tarea; nombres relativos, sin interpolación shell insegura.
- job id, array id si aplica, hostname, timestamps, señal, launcher exacto y versión detectada.
- exit code del proceso no basta para `PASS`; el parser/gate decide.
- salida vacía de `squeue` nunca equivale por sí sola a éxito: reconciliar `sacct`, archivos y checkpoint.
- no borrar ni sobrescribir artefactos; intentos nuevos tienen IDs distintos.

## Dry-run y validación

Dry-run significa cero submit y cero invocación científica. La preparación local puede escribir exclusivamente en un sandbox/paquete de salida declarado; no se implementará mediante monkey-patching global. Deben probarse quoting, recursos inválidos, launchers, señales, exit codes, timeout, falta de `sacct`, cancelación e idempotencia.

## No adoptado

- `module purge/load` incondicional.
- MPI concatenado como string más `-np`.
- `JOB DONE` de QE.
- inferencia de partición por regex de nombres.
- `squeue` vacío → `COMPLETED`.
- auto-inyección `qef --resume` y un `sbatch` por punto.

