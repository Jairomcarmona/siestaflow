# Reporte de validación del contexto

## Veredicto

`CONTEXT_PACKAGE_VALIDATED_WITH_ONE_MISSING_REQUIRED_SOURCE`

El ZIP fue localizado fuera de la raíz de trabajo, copiado como `ROOT/SIESTAFLOW_CONTEXT_v01.zip`, inspeccionado antes de extraerse y extraído en una carpeta `context/` nueva. No se sobrescribió ninguna extracción previa. El directorio envolvente `SIESTAFLOW_CONTEXT/` del ZIP se normalizó para obtener `context/donor/`, `context/scientific_governance/`, `context/siesta_reference/` y `context/scientific_project_snapshot/`.

## Validaciones observadas

| Comprobación | Resultado | Clasificación |
|---|---|---|
| ZIP disponible | 10,357,047 bytes | OBSERVED |
| SHA-256 | `cdfe2f2c054887e40af890f8fceb462e5c4ca4fcd65334c3a5105b2d7ef6afac` | OBSERVED |
| Entradas | 654: 642 archivos, 12 directorios | OBSERVED |
| Rutas absolutas, prefijos de unidad o segmentos `..` | 0 | OBSERVED |
| Verificación posterior contra bytes del ZIP | 642/642 presentes, 0 hashes distintos, 0 extras después de limpiar cachés accidentales | OBSERVED |
| Simulaciones SIESTA/SLURM/SSH | ninguna | OBSERVED |

Las carpetas `donor/`, `scientific_governance/`, `siesta_reference/`, `scientific_project_snapshot/` y `README_CONTEXT.md` ya existían sueltas en `ROOT/` antes de la extracción. Se preservaron sin modificación; no son el `context/` validado ni se usan como workspace mutable.

## Fuentes obligatorias

| Fuente | Ruta dentro de `context/` | Estado y autoridad |
|---|---|---|
| `PROMPT_MASTER_SIESTAFLOW.md` | no está en el ZIP | MISSING. El texto adjunto de la solicitud gobierna este trabajo, pero no se falsea como miembro del paquete. |
| `README_CONTEXT.md` | `README_CONTEXT.md` | OBSERVED; arquitectura y alcance del paquete. |
| `DFT_PROJECT_STATE_FOR_SIESTAFLOW_ORCHESTRATOR.md` | `scientific_governance/` | OBSERVED; autoridad del estado real. |
| `DFT_TECHNICAL_EXECUTION_MANUAL.md` | `scientific_governance/` | OBSERVED; autoridad científica F0–F12. |
| `siesta_manual_official_5.4.2.pdf` | `siesta_reference/` | OBSERVED; autoridad técnica SIESTA 5.4.2. No fue necesaria una interpretación de sintaxis en M0. |
| `siesta_keywords_raw_unvalidated.json` | `siesta_reference/` | OBSERVED; `RAW_REFERENCE_CORPUS`, `NOT_AUTHORITATIVE`, `NOT_SAFE_FOR_AUTOMATIC_FDF_GENERATION`. |
| Donante QEF | `donor/qe-postprocess-framework/` | OBSERVED; referencia de ingeniería de sólo lectura. |
| Snapshot científico | `scientific_project_snapshot/` | OBSERVED; evidencia científica de sólo lectura. |

## Estado científico vinculante preservado

| Campo | Valor |
|---|---|
| `CURRENT_DFT_PROJECT_STATUS` | `SANITY_READY_PENDING_PREFLIGHT` |
| `HIGHEST_SUPPORTED_PHASE` | `F0_PARTIAL` |
| `ORCHESTRATOR_READINESS` | `READY_FOR_GENERIC_HPC_KERNEL` |
| `CONFIRMED_SIESTA_RUNS` | `0` |
| `REAL_SIESTA_OUTPUTS` | `0` |
| `FIRST_SCIENTIFIC_CAMPAIGN` | `CAMPAIGN_01_M1_SANITY` |
| `FIRST_PERSISTENT_CAMPAIGN` | `CAMPAIGN_02_M1_MESH_CONVERGENCE` |

`M1_U0_FM` continúa siendo un sanity independiente pendiente de preflight y autorización; el barrido de `Mesh.Cutoff = 200, 250, 300, 350 Ry` continúa siendo futuro y no ejecutado.

## Incidencia de inmutabilidad

Durante la primera invocación de pytest, el directorio de trabajo apuntó por error al donante extraído. Se generaron únicamente `.pytest_cache/` y tres clases de `__pycache__/`. Se compararon todos los archivos originales con los streams del ZIP: 0 diferencias y 0 ausencias. Se eliminaron exclusivamente esas cachés y una segunda comparación dejó 642/642 archivos exactos y 0 extras. Las ejecuciones válidas posteriores se hicieron sobre una copia temporal con `PYTHONPATH` fijado a su propio `src/`.

## Limitaciones

- `PROMPT_MASTER_SIESTAFLOW.md` es una ausencia real del paquete.
- No se realizó validación remota; no hay SSH, credenciales ni herramientas de clúster disponibles o asumidas.
- No se ejecutó SIESTA ni se interpretó evidencia simulada como evidencia científica.
- El inventario exhaustivo está en `CONTEXT_INVENTORY.md`.

