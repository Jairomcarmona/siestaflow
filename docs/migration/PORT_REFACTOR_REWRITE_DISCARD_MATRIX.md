# Matriz PORT / REFACTOR / REWRITE / DISCARD

Cada fila tiene una sola decisión. `PORT` aplica a una unidad pequeña, no al archivo que la contiene.

| Componente donante | Tags | Decisión | Justificación y destino futuro |
|---|---|---|---|
| Patrón temp + `os.replace` de `_atomic_write_json` | GENERIC_HPC, SIESTA_RELEVANT | PORT | Trasladar con atribución, fsync y pruebas; base de `STATE_STORE`. |
| `log_exception` | GENERIC_HPC | PORT | Decorador pequeño; sanitizar argumentos para no registrar secretos. |
| `ProjectManager.find_root` | GENERIC_HPC, SIESTA_RELEVANT | PORT | Contrato simple de búsqueda ascendente; cambiar centinela/nombre. |
| `ProjectManager` completo | LEGACY, GENERIC_HPC | REFACTOR | Separar esquema, IO, discovery e historial; rutas relativas y validación. |
| `get_semantic_run_dir` | GENERIC_HPC, TECHNICAL_DEBT | REFACTOR | Conservar colisiones `_vNN`; añadir slug, confinamiento y creación transaccional. |
| `WorkspaceManager.import_mass_inputs` | QE_SPECIFIC, SIESTA_RELEVANT | REFACTOR | Conservar staging/mapa atómico; quitar parche QE y errores silenciados. |
| `setup_workspace.create_workspace` | LEGACY, TECHNICAL_DEBT | REWRITE | Contrato útil; implementación sobrescribe y mezcla deploy/código/symlinks. |
| `generate_deploy_kit.py` | QE_SPECIFIC | REWRITE | El destino `REMOTE_VALIDATION_PACKAGER` requiere manifest/hashes, no golden inputs QE. |
| `SlurmConfig` | GENERIC_HPC, TECHNICAL_DEBT | REWRITE | Reemplazar defaults Yoltla/QE y dict mutable por esquema validado. |
| `generate_slurm_script` | QE_SPECIFIC, GENERIC_HPC | REWRITE | Conservar encabezados/fail-fast; introducir worker, quoting, señales y launcher abstracto. |
| `submit_slurm` | GENERIC_HPC | REFACTOR | Parsing/errores útiles; separar `PROCESS_LAUNCHER` y no someter desde flujo local. |
| advisors SLURM | LEGACY, GENERIC_HPC | DISCARD | Inferencias de nombres de partición/Yoltla no son evidencia SIESTA. |
| `qef.core.interfaces` | GENERIC_HPC | REFACTOR | Idea útil, contratos demasiado genéricos para evidencia/gates/launchers. |
| `qef.core.domain` | GENERIC_HPC, TECHNICAL_DEBT | REWRITE | Diccionarios `properties/metadata` sin esquema violan trazabilidad. |
| registro global `_ENGINES` | TECHNICAL_DEBT | DISCARD | Estado global mutable; usar composición/inyección explícita. |
| `QERunner` wrapper | QE_SPECIFIC, TECHNICAL_DEBT | DISCARD | Firma rota y acceso a `_state`; no ofrece contrato trasladable. |
| workflow base/registry | QE_SPECIFIC, GENERIC_HPC | REFACTOR | Conservar plan/validate/analyze; añadir outputs tipados y gates. |
| `ConvergenceSuite` | QE_SPECIFIC, SIESTA_RELEVANT | REWRITE | Conservar “base + variable”; parser/namelist y staging son QE. |
| `ConvergenceController` | QE_SPECIFIC, LEGACY, TECHNICAL_DEBT | REWRITE | Contrato secuencial útil; implementación monolítica, un sbatch/punto y auto-física. |
| `NamelistParser` | QE_SPECIFIC | DISCARD | No sirve para FDF y elimina líneas completas con claves múltiples. |
| `ResilienceEngine` | QE_SPECIFIC, TECHNICAL_DEBT | REWRITE | Conservar clases de fallo; prohibir mutación automática de física/input. |
| harvester/parser/XML QE | QE_SPECIFIC | DISCARD | Formato y marcadores no corresponden a SIESTA. |
| `PseudoManager`/UPF detector | QE_SPECIFIC | DISCARD | UPF y heurísticas QE; SIESTA requiere auditor nuevo PSML/PSF. |
| Janitor | LEGACY, TECHNICAL_DEBT | DISCARD | Borrado no pertenece al MVP y aumenta riesgo de evidencia perdida. |
| `.status.json` helpers | GENERIC_HPC, SIESTA_RELEVANT | REFACTOR | Conservar atomicidad/historial; ampliar estados PASS/REVIEW/FAIL/BLOCKED y CAS. |
| Fake SLURM | GENERIC_HPC, TECHNICAL_DEBT | REFACTOR | Conservar lifecycle; eliminar patch global y modelar stdout/stderr/exit/sacct. |
| golden outputs QE | QE_SPECIFIC | DISCARD | No validarían un parser SIESTA; conservar sólo el patrón de golden tests. |
| smoke test | GENERIC_HPC | REFACTOR | Conservar sandbox y efectos observables; no proclamar aptitud remota. |
| pruebas de proyecto/workspace | GENERIC_HPC | PORT | Trasladar escenarios, no imports QE, y añadir confinamiento/overwrite/crash. |

## Conteo de decisiones

- `PORT`: 4 unidades.
- `REFACTOR`: 9 unidades.
- `REWRITE`: 8 unidades.
- `DISCARD`: 8 unidades.

Los conteos son de filas de esta matriz, no de archivos ni módulos futuros.

