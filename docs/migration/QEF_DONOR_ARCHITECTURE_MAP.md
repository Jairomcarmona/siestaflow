# Mapa de arquitectura del donante QEF

## Alcance observado

El donante es simultáneamente una CLI monolítica de postproceso QE, un árbol `src/qef` parcialmente modernizado y un controlador de convergencia legacy. La versión declarada es contradictoria: `pyproject.toml` indica 0.2.1, `main.py`/documentación usan otras versiones y el controller se presenta como 2.x.

| Zona | Evidencia principal | Comportamiento observado | Relevancia |
|---|---|---|---|
| CLI | `main.py` | init/status/run, configuración, generación, submit, menú interactivo | LEGACY, QE_SPECIFIC |
| Dominio mínimo | `src/qef/core/` | `System`, `Result`, ABC y registro global | GENERIC_HPC, TECHNICAL_DEBT |
| Adaptador QE | `src/qef/engines/qe/` | wrappers sobre legacy; runner usa keywords obsoletas y atributos privados | QE_SPECIFIC, BROKEN |
| Proyecto | `src/qef/legacy/core/project.py` | centinela, búsqueda ascendente, manifiesto, historial | GENERIC_HPC, SIESTA_RELEVANT |
| Workspace | `workspace.py`, `utils.py`, `setup_workspace.py` | importación, nombres/versiones, copias/symlinks, mapa de jobs | GENERIC_HPC con supuestos QE |
| SLURM | `slurm.py`, advisors, controller | render, submit, polling, selección de partición | GENERIC_HPC mezclado con Yoltla/QE |
| Convergencia | `convergence.py`, `convergence_controller.py` | variantes, un `sbatch` por punto, harvest, criterio, resume | QE_SPECIFIC; contrato parcial útil |
| Persistencia | `utils.py`, `project.py`, controller | snapshots JSON con temp+replace; sin event store | GENERIC_HPC, SIESTA_RELEVANT |
| Recuperación | `resilience.py` | clasifica texto `.err` y muta el primer `.in` para restart | QE_SPECIFIC, UNSAFE_FOR_SIESTA |
| Evidencia | harvester, parsers, golden outputs | extracción regex de outputs QE y CSV | QE_SPECIFIC |
| Pruebas | `tests/`, root `test_*.py`, smoke | 272 tests; fake SLURM global; golden QE | patrón reutilizable, fixtures QE descartables |

## Flujo operativo real del donante

1. Descubre o crea proyecto mediante `.qef_project.json`.
2. Parsea un output SCF QE previo y localiza `<prefix>.save`.
3. Crea un run semántico o `run_NNN`, enlaza/copia el `.save`, escribe inputs y metadata.
4. Renderiza un script con pasos QE secuenciales y, si se solicita, invoca `sbatch`.
5. Mantiene `.status.json` local para runs de postproceso.
6. En convergencia, genera una variante, envía **un nuevo job**, espera `squeue`, cosecha CSV y decide el siguiente punto.
7. Guarda `.qef_convergence_state.json` entre transiciones; el modo async añade `qef --resume` al propio script.

Esto no satisface `ONE_SBATCH_MANY_SIESTA_RUNS`: reutiliza lógica de secuencia dentro de un script para pasos de un único workflow, pero el loop adaptativo de convergencia sigue siendo `ONE_POINT_ONE_SBATCH`.

## Proyecto y workspace

- `ProjectManager.find_root()` sube hasta localizar el centinela: comportamiento útil.
- `init_project()` crea seis directorios y un manifiesto, pero su primera escritura no es atómica ni valida esquemas/nombres.
- `get_semantic_run_dir()` resuelve colisiones `_v02`…`_v99`; no confina etiquetas con separadores (`../escaped` sale de `03_runs`).
- `WorkspaceManager.import_mass_inputs()` ordena entradas, parchea `pseudo_dir`, calcula `npool`, crea variantes y actualiza `job_index.map` atómicamente.
- `_copy_dir()` y el deploy kit sobrescriben archivos homónimos pese al mensaje de “sin sobreescribir”.
- Los symlinks apuntan al framework absoluto; el fallback `.pth` no reproduce un archivo enlazado y reduce portabilidad/provenance.

## SLURM

- Encabezados: partition, job-name, nodes, ntasks, ntasks-per-node, time, stdout y stderr con `%j`.
- Entorno: `module purge/load` y `OMP_NUM_THREADS=1` rígidos.
- Launcher: string de configuración, pero el renderer concatena siempre `-np`; algunos defaults ya contienen `-n`, produciendo contratos ambiguos.
- Cada paso captura `$?`; sólo `pw.x` exige `JOB DONE`.
- El submit extrae el último token o un regex de stdout según la ruta de código.
- Polling sólo usa `squeue`; salida vacía se asume `CD`, sin `sacct` ni evidencia de exit code.
- No existen presupuesto de tiempo restante, señales, checkpoint por tarea, gate científico ni separación `ProcessLauncher`.

## Persistencia y recuperación

- Patrones valiosos: temporal en el mismo directorio más `os.replace`; historial de estados; snapshot de configuración; job id.
- Ausencias: esquema versionado estricto, lock/concurrencia, append-only events, manifest de artefactos, fsync, validación de hash al cargar, reconciliación SLURM y migraciones de estado.
- `resume()` advierte una versión distinta pero continúa, y no compara el MD5 almacenado.
- `KeyboardInterrupt` marca toda la fase `FAILED` y no cancela jobs; no hay estado `REVIEW/BLOCKED`.

## Convergencia

- Separa parcialmente generación (`ConvergenceSuite`), dispatch, harvest y criterio.
- Mantiene histories y límites de iteración; orden Ecut → probe → k-grid → Hubbard.
- `_advance_phase()` no valida transiciones.
- Inventa un `PseudoInfo` “mock” si falta, autoelige objetivo Hubbard en dry-run y sugiere un U “golden”: incompatible con gobernanza SIESTAFLOW.
- El dry-run escribe inputs y outputs sintéticos; no es una simulación sin efectos.

## Frontera de migración

Conservar contratos pequeños y demostrables; no trasladar archivos completos. El núcleo futuro debe ser nuevo, tipado, con dependencias inyectadas, políticas científicas fuera de ejecución y launchers explícitos. M0 sólo documenta esa frontera: no crea implementación SIESTA.

