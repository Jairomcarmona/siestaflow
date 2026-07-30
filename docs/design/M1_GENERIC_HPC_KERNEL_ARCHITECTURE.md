# Arquitectura M1: Generic HPC Kernel

## Resultado

M1 implementa un kernel local, tipado y sin adaptador de motor científico. El flujo probado es:

```text
ProjectManager → WorkspaceManager → BasicCampaignPlanner
  → AuthorizationEngine → TimeBudget → LocalFakeLauncher
  → ArtifactStore → GateEngine → EventStore + StateStore
  → siguiente tarea en la misma FakeSlurm allocation o stop
```

## Componentes

| Módulo | Responsabilidad | Clasificación frente a M0 |
|---|---|---|
| `models.py` | modelos/enums tipados y serialización | REWRITE de dicts donor |
| `filesystem.py` | IO explícito, atomicidad, dry-run y path safety | NEW_IMPLEMENTATION; patrón atómico PORT |
| `project.py` | identidad y manifiesto de proyecto | REFACTOR de `ProjectManager` |
| `workspace.py` | campañas/tareas/intentos no sobrescribibles | REFACTOR/REWRITE del workspace donor |
| `storage.py` | state hashado, eventos append-only, artefactos | PORT del patrón replace; EVENT/ARTIFACT NEW_IMPLEMENTATION |
| `authorization.py` | autorización inmutable, hash, vigencia y alcance | NEW_IMPLEMENTATION |
| `gates.py` | PASS/REVIEW/FAIL/BLOCKED genéricos | NEW_IMPLEMENTATION |
| `hpc.py` | interfaces launcher/SLURM, fakes, tiempo y fallos | REWRITE + NEW_IMPLEMENTATION |
| `campaign.py` | planner y secuencia persistente/reanudable | REWRITE del controller donor |

Trazabilidad base: `docs/migration/QEF_DONOR_ARCHITECTURE_MAP.md`, `PORT_REFACTOR_REWRITE_DISCARD_MATRIX.md` y los tres contratos conductuales.

## Propiedades demostradas

- Una campaña usa un solo `allocation_id` para tres tareas secuenciales.
- Toda tarea requiere autorización y tiempo antes de crear su intento.
- Cada intento vive en `attempt_NNN`; resultados anteriores se preservan.
- Toda transición se añade a `events.jsonl` y materializa atómicamente en `state.json`.
- Un estado corrupto o contradictorio con eventos falla cerrado.
- REVIEW/FAIL/BLOCKED detienen; sólo PASS continúa.
- `squeue` ausente se clasifica `TERMINAL_STATE_REQUIRES_EVIDENCE` sin accounting.
- El launcher y SLURM falsos no parchean `subprocess` ni llaman comandos reales.

## Fronteras

`FileSystem`, `ProcessLauncher` y `SlurmClient` son fronteras explícitas. M1 implementa `RealFileSystem`, `DryRunFileSystem`, `LocalFakeLauncher` y `FakeSlurmClient`. Los launchers `srun`, Hydra y `mpirun`, así como un cliente SLURM real, sólo están previstos conceptualmente y no se simulan como validados.

## Persistencia de la asignación

`CampaignState.allocation_id` se conserva. Al reanudar con el mismo fake client se recupera esa asignación y no se somete otra. Una tarea `COMPLETED` se omite; `INTERRUPTED` obtiene un nuevo intento. El patrón prepara `ONE_SBATCH_MANY_SIESTA_RUNS` sin implementar sbatch ni SIESTA.

