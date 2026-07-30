# Arquitectura funcional M2

M2 conserva el kernel M1 y monta SIESTA como adaptador. `EngineAdapter` separa inspección, validación, preparación, comando, output, artefactos y clasificación. `SiestaEngineAdapter` conecta FDF, registro, validador, parser streaming y catálogo de artefactos; `SyntheticSiestaLauncher` es el único launcher SIESTA disponible y no crea procesos.

El flujo local es:

```text
snapshot read-only -> FDFDocument -> InputValidationResult
                   -> CampaignDefinition + AuthorizationEnvelope
                   -> WorkspaceManager -> SyntheticSiestaLauncher
                   -> SiestaOutputRecord -> GateDecision -> StateStore/EventStore
                   -> RemotePackager preview -> RemoteResultImporter
```

`CAMPAIGN_01_M1_SANITY` tiene una tarea, termina tras la compuerta humana y sólo prepara un preview. `CAMPAIGN_02_M1_MESH_CONVERGENCE` usa una autorización `synthetic_only`, cuatro workspaces secuenciales y una asignación falsa; su estado real permanece `BLOCKED_BY_SCIENTIFIC_GATE` hasta `F1_REAL_RUN_COMPLETE`, `F2_OUTPUT_AUDIT_PASS` y `HUMAN_AUTHORIZATION_FOR_F3`.

La persistencia, autorización, compuertas, filesystem y fake SLURM siguen siendo módulos M1. Toda semántica SIESTA vive en `engines/siesta`. El perfil remoto conserva nulos, el comando de motor es configuración y el script preview termina con error hasta configurar el clúster. No existe ruta que invoque SIESTA, MPI, SSH, SLURM real o `sbatch`.

Estado científico conservado: `SANITY_READY_PENDING_PREFLIGHT`, `F0_PARTIAL`, cero corridas confirmadas y cero outputs reales.
