# SIESTAFLOW 0.2 — Estado de consolidación

Fecha de corte: 2026-07-29

Estado: `LOCAL_ACCEPTANCE_PASS / REMOTE_TWO_STAGE_ACCEPTANCE_PENDING`

## Alcance consolidado

- Ejecución MPI mediante `mpiexec.hydra -bootstrap ssh` con lista explícita de
  nodos y procesos por nodo.
- Compatibilidad conservada con `srun`.
- Campañas descritas como DAG con dependencias explícitas.
- Transferencia de artefactos padre-hijo con verificación SHA-256.
- Tareas de decisión (`gate`) acotadas y ejecutadas dentro de la asignación
  Slurm.
- Estados `READY`, `RUNNING`, `COMPLETED`, `FAILED` y `BLOCKED`, con cierre
  seguro ante fallos.
- CLI de progreso y observación sin modificar la campaña.
- Empaquetado autocontenido para Yoltla, incluyendo `progress.sh`.
- Perfil de ejecución de Yoltla y mapa de migración de la campaña de
  birnessita.

## Validación local

- Suite completa: `273 passed`.
- Compilación de módulos Python: aprobada.
- Versión CLI: `siestaflow 0.2.0`.
- Paquete técnico de aceptación: verificado.
- Sintaxis Bash de `submit.slurm` y `progress.sh`: aprobada.

## Aceptación remota pendiente

El paquete `SIESTAFLOW_V02_YOLTLA_TWO_STAGE_ACCEPTANCE.zip` valida en Yoltla,
sin interpretación científica:

1. ejecución SIESTA padre mediante Hydra;
2. producción de un artefacto `DM`;
3. verificación de manifiesto y SHA-256;
4. transferencia del `DM` al cálculo hijo;
5. ejecución del hijo solamente si el padre terminó correctamente.

SHA-256 del ZIP:

`568C31600FB7D7009B537E5F41967DB2536F5312D33B84A66E041F71AFACBFDA`

La ejecución remota no se realizó durante esta consolidación y no se modificó
ningún trabajo científico activo o pendiente en Yoltla.

## Control de versiones

El directorio ya contiene `.git`, pero no existe todavía un commit inicial y
no hay identidad Git configurada. El baseline no fue firmado con una identidad
inventada. Se debe configurar `user.name` y `user.email` antes de crear el
primer commit.

