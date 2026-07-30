# Matriz local de validación de FDF reales con OpenMPI

## Resultado

Estado agregado: `LOCAL_REAL_FDF_MPI_SMOKES_COMPLETE`.

Las tres variantes técnicas están identificadas como `NON_SCIENTIFIC_LOCAL_STATIC_SMOKE` y `SCIENTIFIC_INTERPRETATION_FORBIDDEN`. Se generaron con `SiestaEngineAdapter` y `FDFRenderer`. En cada caso, la comparación semántica y el diff textual contienen un único cambio autorizado:

```text
MD.Steps 300 -> 0
```

Los hashes de los tres FDF originales antes y después coinciden. No se modificaron `MD.TypeOfRun`, geometría, celda, coordenadas, carga, spin, momentos, XC, basis, `Mesh.Cutoff`, k-grid, DFT+U ni pseudopotenciales.

## Selección de recursos

| Campo | Valor |
|---|---|
| CPU | AMD Ryzen 5 7535HS |
| Núcleos físicos | 6 |
| Núcleos lógicos | 12 |
| RAM total expuesta a WSL | 7,779,424 KiB (7.42 GiB) |
| RAM disponible al seleccionar | 7,215,676 KiB (6.88 GiB) |
| Perfil | `local_openmpi_4` |
| Procesos MPI | 4 |
| Ejecutable | `/home/jmc/.local/siesta-5.4.2-openmpi/bin/siesta` |
| Lanzador | `/usr/bin/mpirun` — Open MPI 4.1.6 |

Se eligió `np=4` porque utiliza cuatro de los seis núcleos físicos, deja margen para WSL/Windows, no consume automáticamente los doce hilos lógicos y ya había demostrado estabilidad y mejor tiempo que `np=2` en el smoke C50. No se justificó repetir un benchmark.

## Matriz MPI

| SYSTEM | MPI_TASKS | STATIC_VARIANT | SEMANTIC_DIFF | EXIT_CODE | SCF_STARTED | SCF_CONVERGED | TERMINATION | STATUS | ELAPSED_TIME | MAX_RSS |
|---|---:|---|---|---:|---|---|---|---|---:|---:|
| `SURF_Gr5x5_2COO_v01` | 4 | `83127a6d…c849a` | solo `MD.Steps 300→0` | 0 | sí | sí, 84 iteraciones | `NORMAL_CONVERGED_TERMINATION` | `LOCAL_MPI_SMOKE_CONVERGED` | 1181.39 s | 611292 KiB |
| `ADS_Ca8w_v01` | 4 | `be5319c6…7354` | solo `MD.Steps 300→0` | 1 | sí, 10 iteraciones | no | `CONTROLLED_TECHNICAL_CUTOFF_AFTER_10_SCF_ITERATIONS` | `LOCAL_MPI_TECHNICAL_CHAIN_PASS` | 823.84 s | 13696 KiB* |
| `ADS_Mg6w_v01` | 4 | `7844389d…7ff1` | solo `MD.Steps 300→0` | 1 | sí, 10 iteraciones | no | `CONTROLLED_TECHNICAL_CUTOFF_AFTER_10_SCF_ITERATIONS` | `LOCAL_MPI_TECHNICAL_CHAIN_PASS` | 799.54 s | 13568 KiB* |
| `M0_MnO2_ideal_layer_GOLDEN_v02` | — | no creada | — | — | no | no | `NOT_RUN_NO_APPROVED_FDF` | `INPUT_CONFIGURATION_REVIEW_REQUIRED` | — | — |

Los exit codes 1 de Ca8w y Mg6w fueron producidos deliberadamente al terminar `mpirun` después de diez iteraciones, una vez demostrada la cadena técnica. El parser conserva la clase cruda `TRUNCATED_OUTPUT`; la evidencia adicional conserva la causa externa del corte. No hubo NaN, patrón fatal, fallo MPI, fallo de filesystem ni pseudo ausente. No se presentan como terminaciones normales ni como convergencia.

*En los dos cortes, el RSS de GNU time corresponde a la observación del proceso lanzador después de la señal y no debe interpretarse como RSS agregado de los cuatro ranks. Se conserva el valor crudo solicitado, sin inferir memoria científica ni de producción.

## Identidad verificada

| SYSTEM | ÁTOMOS | COMPOSICIÓN | CARGA | SPIN | PSEUDOS |
|---|---:|---|---:|---|---|
| `SURF_Gr5x5_2COO_v01` | 56 | C52 O4 | -2 | no polarizado | C, O |
| `ADS_Ca8w_v01` | 25 | Ca1 H16 O8 | +2 | no polarizado | Ca, H, O |
| `ADS_Mg6w_v01` | 19 | H12 Mg1 O6 | +2 | no polarizado | H, Mg, O |

Los hashes de geometría, FDF, variante y cada PSML están registrados en `local_validation_matrix.json` y en el `summary.json` de cada run.

## Evidencia aislada

Raíz:

```text
/home/jmc/siestaflow-local-smoke/LOCAL_REAL_FDF_STATIC_SMOKES
```

Run IDs MPI:

- `mpi4-surf-2coo-static-20260722T052222Z`
- `mpi4-ca8w-static-20260722T054250Z`
- `mpi4-mg6w-static-20260722T055700Z`

Cada directorio conserva copias ligadas por hash bajo `input/` y `work/`, además de `results/siesta.out`, `results/siesta.err`, `results/siesta.time`, `evidence/command.json` y `evidence/summary.json`. Los dos cortes técnicos añaden `evidence/technical_cutoff.json`.

La corrida serial previa `surf-2coo-static-20260722T051242Z` no fue reutilizada ni mezclada. Se terminó al cambiar el alcance a MPI y quedó como `CANCELLED_BY_USER`, exit 143, 21 iteraciones y evidencia preservada en `evidence/cancellation.json`.

## Pruebas

- Ejecutor y parser: `46 passed, 0 failed`.
- Suite completa WSL: `235 passed, 9 failed`.
- Los nueve fallos son exactamente el baseline conocido: conteo fijo del ZIP de contexto, ruta Windows de pseudo bajo `pathlib` POSIX y siete casos shell/stubs del runtime remoto.
- Fallos nuevos: 0. Fallos relacionados con estos smokes: 0.

No se modificó el framework, no se recompiló SIESTA, no se ejecutó M0 y no se usaron SSH, Yoltla, SLURM ni `sbatch`. No se interpretaron ni compararon energías.
