# Trazabilidad auditoría DFT → donante → destino

Etiquetas de evidencia: `OBSERVED`, `DOCUMENTED_ONLY`, `INFERRED`, `MISSING`, `CONTRADICTORY`. “Prueba” refiere a `siestaflow/tests/characterization/`; `future:*` significa prueba requerida pero no creada en M0.

| Requisito MVP | Evidencia auditoría DFT | Componente donante relacionado | Decisión | Módulo futuro | Funcionalidad faltante | Prueba |
|---|---|---|---|---|---|---|
| PROJECT_MANAGER | OBSERVED geometrías/FDF con identidad; F0 parcial | `ProjectManager` | REFACTOR | `project_manager` | schema, IDs, authority/status locks | workspace; future:project_schema |
| WORKSPACE_MANAGER | DOCUMENTED_ONLY separación local/remota/contexto | `WorkspaceManager`, naming | REFACTOR | `workspace_manager` | confinement, transactional staging, no-overwrite | workspace |
| FDF_PARSER | OBSERVED 9 FDF; manual 5.4.2 autoridad | NO_DONOR_EQUIVALENT (namelist QE no equivale) | REWRITE | `siesta/fdf_parser` | includes/blocks/units/provenance | future:fdf_golden |
| FDF_VARIANT_GENERATOR | DOCUMENTED_ONLY mesh 200/250/300/350 | `ConvergenceSuite` sólo como patrón | REWRITE | `siesta/fdf_variant_generator` | delta explícito, locks científicos, hashes | future:mesh_variants |
| INPUT_VALIDATOR | OBSERVED sanity candidato; preflight pendiente | QE validator no equivalente semántico | REWRITE | `siesta/input_validator` | manual-backed syntax + scientific constraints | future:input_validation |
| PSEUDOPOTENTIAL_AUDITOR | MISSING pseudos empaquetados; hashes externos documentados | UPF detector | DISCARD | `siesta/pseudopotential_auditor` | PSML/PSF family/XC/species/hash checks | future:pseudo_manifest |
| SIESTA_OUTPUT_PARSER | MISSING outputs SIESTA = 0 | QE parser/harvester no equivalente | DISCARD | `siesta/output_parser` | termination, SCF, warnings, motion, artifacts | future:real_golden_outputs |
| CAMPAIGN_PLANNER | DOCUMENTED_ONLY fases/dependencias | workflows/controller parcial | REWRITE | `campaign/planner` | typed DAG, authorization, no phase skips | future:phase_graph |
| PERSISTENT_ALLOCATION_WORKER | DOCUMENTED_ONLY one sbatch many runs | NO_DONOR_EQUIVALENT; controller es un sbatch/punto | REWRITE | `execution/allocation_worker` | in-allocation loop, signals, checkpoints, gates | future:persistent_worker |
| SLURM_SCRIPT_RENDERER | MISSING perfil SIESTA; headers donor observed | `generate_slurm_script` | REWRITE | `execution/slurm_renderer` | worker command, quoting, signals, no QE defaults | slurm; future:snapshots |
| PROCESS_LAUNCHER | MISSING launcher SIESTA/Yoltla | MPI string en `SlurmConfig` | REWRITE | `execution/launchers` | cinco launchers, argv/env/result contract | slurm; future:launchers |
| TIME_BUDGET | DOCUMENTED_ONLY aprovechar walltime | NO_DONOR_EQUIVALENT | REWRITE | `execution/time_budget` | remaining time, estimates, safety margin | future:time_budget |
| GATE_ENGINE | DOCUMENTED_ONLY PASS/REVIEW/FAIL/BLOCKED y gates F0–F12 | shields/controller no equivalente científico | REWRITE | `science/gate_engine` | deterministic rules, unknown→REVIEW | future:gates |
| AUTHORIZATION_ENGINE | DOCUMENTED_ONLY sanity y transiciones humanas | prompts donor parciales | REWRITE | `science/authorization_engine` | signed/scoped decisions; REVIEW≠PASS | future:authorization |
| STATE_STORE | DOCUMENTED_ONLY checkpoint persistente | atomic JSON/controller state | REFACTOR | `evidence/state_store` | schema, CAS, integrity, migrations | persistence |
| EVENT_STORE | DOCUMENTED_ONLY trazabilidad | NO_DONOR_EQUIVALENT (logs no son event store) | REWRITE | `evidence/event_store` | append-only ordered decisions | future:event_replay |
| ARTIFACT_STORE | OBSERVED hashes necesarios; outputs ausentes | metadata/harvester parciales | REWRITE | `evidence/artifact_store` | immutable manifests, content hashes, attempts | future:artifact_integrity |
| RESTART_MANAGER | MISSING compatibilidad restart SIESTA | `ResilienceEngine` QE | REWRITE | `execution/restart_manager` | SIESTA-aware policy, no physics mutation | future:restart_policy |
| FAILURE_CLASSIFIER | DOCUMENTED_ONLY recursos no cambian física | resilience + SLURM states | REFACTOR | `execution/failure_classifier` | typed evidence, unknown→REVIEW, sacct | future:failure_catalog |
| REPORT_GENERATOR | DOCUMENTED_ONLY auditoría local/remota | audit report/harvester CSV | REFACTOR | `evidence/report_generator` | status labels, sources, immutable links | future:report_golden |
| REMOTE_VALIDATION_PACKAGER | DOCUMENTED_ONLY transferencia manual | deploy kit generator | REWRITE | `packaging/remote_validation` | reproducible bundle, hashes, instructions, import | future:package_roundtrip |

## Requisitos transversales

| Requisito | Evidencia | Resolución M0 |
|---|---|---|
| Primer run único `M1_U0_FM` y stop humano | OBSERVED FDF candidato; DOCUMENTED_ONLY ejecución | excluido de worker persistente inicial |
| Primera persistencia: mesh 200–350 Ry | DOCUMENTED_ONLY | mapear, no generar ni ejecutar |
| No promoción de estado | OBSERVED 0 runs/outputs | valores preservados en validación |
| No SSH/credenciales | flujo operativo vinculante | ningún componente remoto automático |
| Warnings desconocidos | regla científica | futuro parser los convierte en REVIEW |
| OS→IS/WB/hidratación | regla científica | futuro gate humano; NO_DONOR_EQUIVALENT |
| U/spin/carga no automáticos | regla científica | lógica auto-Hubbard donor descartada |

## Resultado de cobertura

Los 21 componentes previstos están mapeados. Cuatro filas declaran explícitamente `NO_DONOR_EQUIVALENT` (`FDF_PARSER`, `PERSISTENT_ALLOCATION_WORKER`, `TIME_BUDGET` y `EVENT_STORE`); otras filas distinguen patrones QE relacionados de equivalentes SIESTA reales. No se inventaron equivalencias. M0 no implementa ninguno de los módulos objetivo.
