# Deuda técnica conocida del donante

| Deuda | Evidencia | Impacto | Tratamiento |
|---|---|---|---|
| Acoplamiento fuerte a QE | `pw.x`, namelists, UPF, `.save`, `JOB DONE` | semántica errónea para SIESTA | DISCARD/REWRITE |
| Legacy y moderno mezclados | root modules + `src/qef/legacy` + wrappers | imports ambiguos, APIs duplicadas | REWRITE frontera |
| Parsers regex | parser, harvester, validators | fragilidad y contexto insuficiente | parser estructurado + golden |
| Atributos privados | `QERunner` lee `ctrl._state` | contrato frágil | DISCARD wrapper |
| Dicts sin esquema | `System.properties`, state/config/metadata | claves/estados no verificables | modelos versionados |
| Monkey-patching global | `audit_workspace`, Fake SLURM | oculta operaciones ajenas, no paralelo | inyección de dependencias |
| Dry-run incompleto | `Path.write_text` funciona dentro del audit; controller crea synthetic output | falsa seguridad/efectos laterales | sandbox explícito |
| Launcher rígido | string MPI + `-np` añadido; defaults inconsistentes | comandos inválidos/no portables | `ProcessLauncher` |
| Un sbatch por punto | controller `_dispatch_to_slurm` en cada iteración | viola requisito principal | worker persistente nuevo |
| Borrado/sobrescritura | Janitor, `prepare_save`, `_copy_dir`, `--force` | pérdida de evidencia | no-overwrite/attempt IDs |
| Configuración monolítica | defaults CLI/QE/Yoltla | capas mezcladas | schemas por capa |
| Cambios automáticos de física | pseudo mock, cutoff derivado, Hubbard target/range, restart mutation | viola gobernanza | autorización/gates |
| Tests sin efectos laterales completos | strings, mocks privados, smoke proclama “apto Yoltla” | falso positivo | assertions de filesystem/evidence |
| Escape de workspace | `get_semantic_run_dir('../escaped',...)` | escritura fuera de raíz | path confinement |
| Errores silenciados | workspace incrementa `errors` sin detalle; catches amplios | auditoría incompleta | errores tipados/eventos |
| Checksum no verificado | `resume()` ignora `integrity` | reanuda estado alterado | SHA-256 validado |
| Versión incompatible tolerada | warning y continúa | corrupción semántica | migración o BLOCKED |
| `squeue` vacío = éxito | `_wait_for_job` retorna CD | falso completed | `sacct`+artefactos+exit |
| Transiciones no validadas | `_advance_phase` explícitamente delega al caller | salto de fases | máquina de estados cerrada |
| Adapter moderno roto | keywords `workspace/base_input/...` no coinciden con constructor | facade no ejecutable | DISCARD |
| Contaminación de imports | primera copia temporal importó otro checkout instalado | tests sobre código equivocado | venv + path assertion |
| Sin event/artifact store | sólo snapshots/CSV/log | provenance parcial | stores separados |
| Sin time budget | no consulta tiempo restante | inicia trabajo que no cabe | `TIME_BUDGET` |
| Shell sin quoting | `cd`, paths, módulos/comandos interpolados | inyección/espacios | argv/quoting estricto |

## Contradicciones documentales

- `setup_workspace.py` dice completar sin sobrescribir; `_copy_dir()` usa `copy2` sobre destinos existentes.
- documentación describe dry-run “completo”; el context manager no intercepta `open` ni `Path.write_text`.
- el smoke imprime “apto para despliegue en Yoltla” pese a no ejecutar SLURM/QE remoto.
- `pyproject.toml` 0.2.1, manifest/CLI 0.7/1.5 y controller 2.x carecen de una versión coherente.
- docstring de `QERunner` promete adapter funcional, pero su llamada al constructor falla.

## Riesgos científicos que no se heredan

No se autoelige U, spin, carga, pseudopotencial, launcher, cutoff ni topology; no se interpreta un sanity como resultado; `REVIEW` no pasa; fallos de recursos no alteran física; pérdida de hidratación y cambios OS→IS/WB requieren revisión humana. Estas reglas proceden de la autoridad DFT, no del donante.

