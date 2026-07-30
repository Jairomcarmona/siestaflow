# Demostración funcional M2

Ejecutada localmente el 2026-07-20. Directorio temporal: `tmp/m2_demo`; paquete entregable: `remote_validation/CAMPAIGN_01_M1_SANITY`. Todas las salidas son sintéticas.

## Sanity end-to-end

1. `fdf inspect` observó SHA-256 `714d16dabd1732f0d21ac8d7947abc2d00748fce509b1a052e3e31c2c9ebc35c`, round-trip exacto, 26 escalares, cinco bloques, cero includes/desconocidos/diagnósticos.
2. `input validate` produjo `PASS`, 54 átomos, especies `Mn/O` y system ID `M1_U0_FM_PILOT`.
3. `campaign create m1-sanity` creó `CAMPAIGN_01_M1_SANITY` con estado `EXECUTION_READY_PENDING_PREFLIGHT` y `real_execution_authorized=false`.
4. `campaign simulate` utilizó una asignación falsa, una tarea y terminó `PASS` técnico.
5. El flujo señaló `human_gate_after_task=true` y no continuó a ciencia ni remoto.
6. `remote package` generó 16 archivos, estado `PREVIEW_WITH_UNVERIFIED_PROFILE`, input hash verificado, nulos explícitos y preflight bloqueante.
7. Se creó un bundle sintético con output normal, eventos, artefactos, manifiesto y checksums.
8. `remote results import` verificó hashes/campaña, preservó `original_bundle`, clasificó `COMPLETED/PASS` y produjo `REMOTE_RESULTS_IMPORTED`.
9. El reporte conserva `synthetic=true`, `PROVISIONAL_UNTIL_REAL_OUTPUT_IMPORTED` y `SYNTHETIC_BUNDLE_NOT_REAL_EVIDENCE`; no promovió evidencia real.

## Mesh persistente

1. `campaign create m1-mesh --preview` creó cuatro variantes 200/250/300/350 Ry y mantuvo `BLOCKED_BY_SCIENTIFIC_GATE`.
2. Las dependencias ausentes son `F1_REAL_RUN_COMPLETE`, `F2_OUTPUT_AUDIT_PASS` y `HUMAN_AUTHORIZATION_FOR_F3`; `real_execution_authorized=false`.
3. Con autorización exclusivamente sintética, `campaign simulate` ejecutó cuatro tareas secuenciales en una asignación falsa.
4. Cada tarea obtuvo workspace `attempt_001`, persistencia atómica y gate `PASS`; no hubo envío adicional.
5. La segunda invocación reanudó con cero asignaciones nuevas, cero launches y cero `attempt_002`.

Resultado: `SANITY_END_TO_END_LOCAL_PASS`, `PERSISTENT_MESH_SIMULATION_PASS`, `ONE_FAKE_ALLOCATION`, `FOUR_SIESTA_TASKS`, `NO_ADDITIONAL_SBATCH`, `FOUR_SEPARATE_WORKSPACES`, `ATOMIC_CHECKPOINT_AFTER_EACH_TASK` y `RESUME_WITHOUT_DUPLICATES`.

No se ejecutó SIESTA, MPI, SSH, SLURM real ni el paquete remoto.
