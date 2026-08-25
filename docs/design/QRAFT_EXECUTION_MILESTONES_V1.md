# QRAFT — Execution Milestones V1

Estado: secuencia vinculante de implementación

Este documento congela la ruta de ejecución desde el baseline `d5f0397`
(`docs: define DAG execution unification seam`). Complementa, y no sustituye,
la columna vertebral, los ADR aceptados ni el roadmap.

## Jerarquía documental

```text
QRAFT_BACKBONE.md
    ↓ invariantes estables
ADR/
    ↓ decisiones arquitectónicas
QRAFT_EXECUTION_MILESTONES_V1.md
    ↓ secuencia vinculante de implementación y gates
QRAFT_PRODUCT_ROADMAP.md
    ↓ estado mutable de producto y versiones
validation/
    ↓ evidencia de cumplimiento
```

Los estados históricos del roadmap no sustituyen los gates de este documento.
ADR-0001, ADR-0002 y ADR-0003 continúan gobernando ruta canónica, authoring
por capabilities/recetas y composición por fragmentos, respectivamente.

## Baseline congelado

La auditoría en `d5f0397` estableció, sin reinterpretación:

- `CompiledWorkflow` / DAG: buena base.
- `CapabilityRegistry`: existe y es contract-driven; aún no es frontera runtime
  universal.
- `AllocationController`: primitives fuertes de fallo/recovery, pero demasiado
  consciente de SIESTA.
- `ConvergenceProtocol`: funcional, pero posee un loop directo de ejecución.
- `single_fdf`: funcional, pero autoridad runtime separada.
- Autoridad global de ejecución: parcialmente unificada.

Dependency ordering, fan-out, branch isolation, dependent blocking, artifact
handoff y recovery son `PASS` en la evidencia preservada. `F02 DAG governed`
es `NO` y `GLOBAL UNIFICATION` es `PARTIAL`.

## Arquitectura objetivo

```text
Scientific Protocol / Recipe                 describe WHAT
          ↓
WorkflowDefinition → CompiledWorkflow
          ↓
Generic DAG Runtime
  dependencies · states · attempts · retries · recovery
  failure propagation · artifact routing · resource coordination
          ↓
CapabilityRegistry
          ↓
Implementation: prepare · command · parser · artifact discovery
                · result classification
          ↓
Normalized NodeResult → Generic DAG Runtime
```

El DAG es ciego a la física concreta y el Generic DAG Runtime es ciego al
engine concreto.

## Responsabilidades por capa

| Capa | Sí posee | No posee |
|---|---|---|
| Scientific Protocol / Recipe | Operación científica, nodos, métricas, regla, selección | Procesos, loops de ejecución, Slurm, attempts, recovery, parsear stdout, copia manual de artefactos |
| DAG / CompiledWorkflow | Nodos, task kind, `capability_id`, dependencias, aristas CONTROL/ARTIFACT, I/O tipados, recursos, settings, topología | SIESTA, SCF, DOS/PDOS/bands, Hubbard U, Slurm, Hydra, OpenMPI, `SiestaOutputParser` |
| Generic DAG Runtime | READY/RUNNING/COMPLETED/FAILED/BLOCKED/INTERRUPTED, attempts, retry, recovery, release/bloqueo, handoff, recursos, evidencia | SCF, DM, DOS, Hubbard U y parsers de engine |
| Capability / Engine Plugin | I/O contracts, `prepare_task`, `build_command`, `parse_output`, `discover_artifacts`, `classify_result`, semántica técnica engine | Topología global, scheduler genérico o decisión científica |
| Scheduler / Launcher / Infrastructure | Slurm, allocation, hosts, MPI, Hydra, OpenMPI, `srun`, recursos, entorno | Decisiones científicas |

`SiestaOutputParser` pertenece al capability/plugin SIESTA. El `NodeResult`
normalizado vuelve al runtime, que gobierna el estado sin conocer física ni
engine.

## Invariantes de modularidad

Una capability nueva (`qraft.siesta.bands`, `qraft.siesta.relax` u otra) sólo
requiere descriptor, contracts, implementation, registration,
recipe/workflow-builder y tests. No modifica `CompiledWorkflow`, Generic DAG
Runtime, allocation scheduling semantics ni recovery state machine.

Un engine futuro (Quantum ESPRESSO, ABINIT, VASP u otro) no modifica DAG,
dependency/attempt/recovery engine ni scientific protocol machinery. Si una
semántica específica lo exige, el architecture gate falla. Corregir un parser
preservando su contrato no modifica DAG, scheduler, recovery, `CampaignSpec`
ni protocolos no relacionados. Cambiar OpenMPI, Hydra o `srun` no modifica
`ScientificIdentity` ni lógica científica.

> Ningún milestone posterior puede introducir una nueva ruta de ejecución de producción. Toda funcionalidad nueva debe atravesar la trayectoria canónica establecida por el milestone anterior.

> Si una nueva funcionalidad no puede expresarse mediante los contratos existentes, se detiene la implementación. Primero debe evaluarse si falta una extensión legítima del contrato; cualquier cambio incompatible o cambio de responsabilidad entre capas requiere ADR.

> No se crea un executor, parser pipeline, recovery mechanism, artifact router o state machine específico por protocolo científico.

## Gobierno

Los únicos estados son `NOT_STARTED`, `IN_PROGRESS`, `PARTIAL`, `BLOCKED`,
`CLOSED` y `DEFERRED`. Código existente no cierra un milestone: sólo evidencia
verificable. No inicia implementación de N+1 hasta que N sea `CLOSED`, salvo
documentación o fixtures sin ruta de producción paralela.

Si aparece un defecto grave anterior, se reabre ese milestone, se registra la
razón, se corrige en la capa propietaria y se revalidan supuestos downstream.
No se parchea en la capa siguiente. Cada cierre crea
`docs/validation/<milestone_name>/`; se prefieren `README.md`, `RESULT.md`,
`evidence/test_results.json`, `evidence/commands.txt` y hashes cuando aporten
valor. La evidencia anterior se referencia, no se duplica.

| Defecto | Capa propietaria |
|---|---|
| Parser | Engine/plugin |
| Scheduler | Scheduler/launcher |
| Recovery | Generic runtime |
| Topología | Compiler/DAG |
| Criterio científico | Protocol/rule |
| Presentación CLI | Interface/output |

Un módulo científico nuevo, después de M1, no justifica cambiar
`CompiledWorkflow`, Generic DAG Runtime, attempt/recovery state machines ni
artifact routing. Si parece necesario: STOP; demostrar contract gap; evaluar
adapter/plugin; crear ADR si sigue siendo necesario; sólo entonces cambiar
core. Este freeze no crea ADR: no contradice decisiones aceptadas.

| Nivel | Política |
|---|---|
| 1 | Unit/integration: Windows/WSL |
| 2 | Runtime científico real: WSL + SIESTA real + MPI + Slurm local |
| 3 | Aceptación HPC inevitable: Yoltla |

Yoltla sólo demuestra multinodo Slurm real, Hydra, módulos institucionales,
filesystem compartido, allocation continuation y launcher/backend equivalence.
No se usa para parser/DAG/scientific debugging ni unit validation. El usuario
transfiere y ejecuta manualmente: no SSH del agente, credenciales ni acceso
remoto autónomo.

## Milestones

Todos los milestones siguientes registran objetivo, entry criteria, scope,
non-goals, acceptance gates, evidence, status y closing commit.

### M0 — Execution Architecture Freeze

| Campo | Definición |
|---|---|
| Objetivo | Congelar baseline, responsabilidades, trayectoria, invariantes, gates y gobernanza. |
| Entry criteria | HEAD `d5f0397`; auditorías DAG revisadas. |
| Scope | Este documento, referencias mínimas, deuda P1 y evidencia M0. |
| Non-goals | Código, schemas, runtime, parser, protocolo, SIESTA, Slurm, ADR. |
| Acceptance gates | Documento aceptado, roadmap lo referencia, no hay cambios fuente, validación documental pasa. |
| Required evidence | `docs/validation/m0_execution_architecture_freeze_v1/`. |
| Status | `CLOSED` |
| Closing commit | Este commit: `docs: freeze QRAFT execution milestones v1`. |

### M1 — Generic DAG Runtime + Capability Boundary

| Campo | Definición |
|---|---|
| Objetivo | `CompiledWorkflow → Generic DAG Runtime → CapabilityRegistry → implementation → NodeResult`. |
| Entry criteria | M0 cerrado. |
| Scope | Seam real, resolución `capability_id`, controller genérico sin semántica SIESTA, ownership único de Attempt, validation lifecycle y recovery. |
| Non-goals | Protocolo nuevo, relax, DOS, LR-U, screening. |
| Acceptance gates | Capability sintética nueva ejecuta sin modificar DAG/core scheduling; Generic Runtime no importa `SiestaOutputParser`. |
| Required evidence | Capability sintética, contract/dependency/lifecycle/recovery tests y `docs/validation/m1_universal_runtime/`. |
| Status | `CLOSED` |
| Closing commit | Este commit: `fix: enforce final M1 runtime invariants`; cierre `ae794f1` y checkpoint `4964e9c` preservados. |

### M2 — F02 Convergence Through Canonical DAG

| Campo | Definición |
|---|---|
| Objetivo | Migrar convergencia simple a M1 y eliminar su autoridad de ejecución. |
| Entry criteria | M1 cerrado. |
| Scope | Protocol conserva puntos, métricas, criterio, selección y decisión científica; runtime ejecuta. |
| Non-goals | Cambiar metodología o física. |
| Acceptance gates | Mismo resultado, punto, `ScientificIdentity`, validación técnica, attempts, recovery/reuse y resultado usuario; `for point in points: execute_fdf_plan(...)` no es autoridad. |
| Required evidence | Comparación before/after y `docs/validation/m2_f02_canonical_dag/`. |
| Status | `CLOSED` |
| Closing commit | `feat: route F02 convergence through canonical DAG`. |

### M3 — Generic Composition + Failure Model

| Campo | Definición |
|---|---|
| Objetivo | Demostrar que M1/M2 no son solución especial de convergence. |
| Entry criteria | M2 cerrado. |
| Scope | `A → artifact → B`; `ROOT → {A,B,C}`; A PASS/B FAIL/C PASS; padre fallido→hijo BLOCKED; interruption/retry; restart/reuse; allocation rollover. |
| Non-goals | Física nueva. |
| Acceptance gates | Fan-out, fan-in cuando aplique, artifact contracts, branch isolation, dependent blocking y recovery. |
| Required evidence | Fixtures genéricos y `docs/validation/m3_generic_composition_failure_model/`. |
| Status | `CLOSED` |
| Closing commit | `test: close M3 generic composition failure model`. |

### M4 — F03 Chained Numerical Convergence

| Campo | Definición |
|---|---|
| Objetivo | basis → accepted basis → mesh → accepted mesh → k-point → `NumericalProfileArtifact`. |
| Entry criteria | M3 cerrado. |
| Scope | Workflow compuesto con contratos tipados/hash-bound. |
| Non-goals | Relax, propiedades electrónicas, LR-U. |
| Acceptance gates | Salida seleccionada N es input exacto typed/hash-bound de N+1. |
| Required evidence | Handoff por etapa y `docs/validation/m4_f03_chained_numerical_convergence/`. |
| Status | `CLOSED` |
| Closing commit | `feat: add F03 chained numerical convergence`. |

### M5 — Relaxation Capability V1

| Campo | Definición |
|---|---|
| Objetivo | `GeometryArtifact → RelaxationCapability → GeometryArtifact`. |
| Entry criteria | M4 cerrado. |
| Scope | Fixed-cell, geometría final, fuerzas, provenance. |
| Non-goals | Variable-cell y staged relaxation antes de cerrar base. |
| Acceptance gates | Pasan fixed-cell, final geometry extraction, forces validation y artifact provenance. |
| Required evidence | `docs/validation/m5_relaxation_capability_v1/`. |
| Status | `CLOSED` |
| Closing commit | `feat: add fixed-cell relaxation capability v1`. |

### M6 — Ground-State Chain

| Campo | Definición |
|---|---|
| Objetivo | numerical convergence → relaxation → final SCF → `ElectronicStateArtifact`. |
| Entry criteria | M5 cerrado. |
| Scope | Cadena reproducible de estado base. |
| Non-goals | Fan-out de propiedades. |
| Acceptance gates | Input renderizado de cada hijo deriva de output typed/hash-bound padre + settings declarados. |
| Required evidence | `docs/validation/m6_ground_state_chain/`. |
| Status | `CLOSED` |
| Closing commit | `feat: add reproducible ground-state chain`. |

### M7 — Electronic Property Fan-out

| Campo | Definición |
|---|---|
| Objetivo | `final SCF → {DOS, PDOS, BANDS}`. |
| Entry criteria | M6 cerrado. |
| Scope | Capabilities de propiedades como ramas independientes. |
| Non-goals | Autoridad nueva o ramas especiales en runtime. |
| Acceptance gates | Añadir DOS/PDOS/BANDS requiere cero nueva execution authority y cero special-case branch; el fallo de una rama no mata hermanas. |
| Required evidence | `docs/validation/m7_electronic_property_fanout/`. |
| Status | `CLOSED` |
| Closing commit | `docs: close M7 electronic property fanout`. |

### M8 — Magnetic / Noncollinear / SOC Workflows

| Campo | Definición |
|---|---|
| Objetivo | initial structure → `{FM, AFM1, AFM2}` → comparison/selection → selected state; luego non-collinear/SOC. |
| Entry criteria | M7 cerrado. |
| Scope | Capabilities/recipes sobre runtime existente. |
| Non-goals | Infraestructura de ejecución magnética. |
| Acceptance gates | Mismos contratos, attempts/recovery y aislamiento. |
| Required evidence | `docs/validation/m8_magnetic_noncollinear_soc/`. |
| Status | `CLOSED` |
| Closing commit | `feat: close M8 integrated magnetic workflow` (integrated M8-D closure). |

### M9 — Mass Screening Scale Acceptance

| Campo | Definición |
|---|---|
| Objetivo | Escala progresiva 10, 25, 100, 500 o equivalente justificado. |
| Entry criteria | M8 cerrado. |
| Scope | Scheduler throughput, persistencia, recovery cost, filesystem/evidence, isolation, summaries, memoria/runtime. |
| Non-goals | Física nueva. |
| Acceptance gates | Summary: `candidate_id`, status, métrica científica, razón rechazo y rank cuando aplique. |
| Required evidence | Mediciones y `docs/validation/m9_mass_screening_scale_acceptance/`. |
| Status | `CLOSED` |
| Closing commit | `feat: close M9 mass screening scale acceptance` |

### M10 — HPC Portability / Production Acceptance

| Campo | Definición |
|---|---|
| Objetivo | Aceptar sólo límites HPC que WSL no demuestra. |
| Entry criteria | M9 cerrado. |
| Scope | Slurm multinodo, Hydra, módulos, shared filesystem, allocation continuation, launcher/backend equivalence. |
| Non-goals | Parser/DAG/scientific debug o unit testing en Yoltla. |
| Acceptance gates | Mismos scientific contracts y workflow identity; diferente `ExecutionSpec` permitido. |
| Required evidence | Expediente manual Yoltla y `docs/validation/m10_hpc_portability_production_acceptance/`. |
| Status | `NOT_STARTED` |
| Closing commit | No aplicable hasta cierre. |

## DFT+U / LR-U

```text
DFT+U / LR-U AUTOMATED WORKFLOW
STATUS: DEFERRED_BY_PROJECT_DECISION
```

La metodología científica/orchestrator sigue finalizándose. Al congelarse,
entra como capabilities + recipe/workflow sobre el runtime aceptado, sin nueva
infraestructura de ejecución.

## Estado vigente de milestones

| Milestone | Estado |
|---|---|
| M0 | `CLOSED` |
| M1 | `CLOSED` |
| M2 | `CLOSED` |
| M3 | `CLOSED` |
| M4 | `CLOSED` |
| M5 | `CLOSED` |
| M6 | `CLOSED` |
| M7 | `CLOSED` |
| M8 | `CLOSED` |
| M9 | `CLOSED` |
| M10 | `NOT_STARTED` |
| DFT+U / LR-U | `DEFERRED` |

Un agente futuro debe construir sólo el siguiente milestone abierto, en la capa
propietaria, con sus gates y evidencia; nunca inferir una ruta paralela ni
promover trabajo histórico a cierre.
