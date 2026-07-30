# Campaña M1/MnO₂ para Yoltla — V2

Paquete auditado para mantener una cola interna de cálculos SIESTA dentro de
una asignación Slurm. Ningún programa del paquete envía trabajos
automáticamente: `automatic_submission=false`.

## Estado

- Integridad y ciencia local: verificadas.
- PSML de Mn y O: incluidos en el ZIP y fijados por SHA-256.
- Perfil preferente: `qz2d-128p`, 2 nodos, 80 tareas, 40 por nodo, 2 días.
- Backend propuesto para Yoltla: `mpiexec.hydra -bootstrap ssh`.
- Compatibilidad remota: **no demostrada localmente**. Requiere evidencia
  actual, aprobación explícita, `sbatch --test-only` y preflight dentro del
  ticket.
- No se declara `READY_FOR_SBATCH`.

La inclusión de los PSML aplica la instrucción directa del usuario y sustituye
la política opcional de exclusión descrita en el punto 16 del encargo.

## Bundles

1. `00_scaling_calibration`: pruebas técnicas 20/40/80 MPI. No autoriza
   interpretación científica ni selección automática.
2. `01_sanity_03a_mesh`: sanity seguido, solo si pasa una compuerta técnica
   automática, por 200/250/300/350 Ry. Requiere F0 y layout aceptado.
3. `03b_kgrid`: 2×2×1, 3×3×1 y 4×4×1 después de que una persona acepte la
   malla en F3A.

F3C, U/espín, relajación, electrónica y complejos siguen bloqueados porque sus
políticas científicas ejecutables no están firmadas. El paquete no inventa
proyectores DFT+U, tolerancias, restricciones ni tratamiento de carga.

## Garantías operativas

- Estado persistente en `state/`, intentos aislados en `work/`, trazas en
  `evidence/` y resumen en `results/`.
- Reintentos transitorios dentro de la misma asignación; fallos deterministas
  de SCF o entrada son terminales.
- Reservas explícitas por nodo y rango de slots, sin solapamiento.
- Reanudación sin repetir un resultado completado cuya evidencia siga válida.
- Detención de nuevos lanzamientos al alcanzar el margen de walltime.
- Versión SIESTA exactamente `5.4.2`, comprobada también mediante MPI.
- Hydra nunca usa `-bootstrap slurm`.

Consulte [DEPLOY_TO_YOLTLA.md](DEPLOY_TO_YOLTLA.md) para el procedimiento y
[RESOURCE_LAYOUT_DECISION.md](RESOURCE_LAYOUT_DECISION.md) para la decisión de
recursos.
