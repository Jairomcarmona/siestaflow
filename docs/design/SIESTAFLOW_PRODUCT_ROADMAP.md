# Roadmap de producto de SIESTAFLOW

Estado del roadmap: 2026-08-01
Estado del software: SIESTAFLOW 0.2 alpha
Estado vinculante: `REMOTE_RUNTIME_DEBT_REMEDIATED / HUMAN_DECISION_PENDING`

Este documento registra estado mutable, prioridades y dependencias. Los
principios estables pertenecen a
[`SIESTAFLOW_BACKBONE.md`](SIESTAFLOW_BACKBONE.md) y el detalle del corte 0.2 a
[`SIESTAFLOW_0_2_RELEASE_STATUS.md`](SIESTAFLOW_0_2_RELEASE_STATUS.md).

## Prioridad y dependencia crítica

El camino remoto positivo de Fase 3 fue completado por el job Yoltla `781100`
y su matriz adversarial técnica por el job `781102`. La trayectoria positiva
verificada fue:

```text
workflow.lock.json
→ run prepare
→ paquete autocontenido
→ sbatch manual en Yoltla
→ 01_parent
→ DM producida y verificada
→ transferencia padre-hijo
→ evidencia de lectura de DM por SIESTA
→ 02_restart_from_parent_dm
→ reconciliación e importación de evidencia
```

La auditoría independiente emitió `CONDITIONALLY_APPROVED` y sus límites de
runtime fueron remediados con evidencia remota adicional. La prioridad restante
es la aceptación humana formal de la transición. El trabajo local que no
interfiera con este gate puede continuar, pero no se amplía el alcance
científico para sustituirla.

## Estado por fase

| Fase | Estado comprobado | Implementado o parcial | Cierre pendiente |
|---|---|---|---|
| 0 — Contratos | `LOCAL_VERTICAL_IMPLEMENTED` | Core Contracts 1.0, envelopes, artefactos, ejecución, eventos, validación, plugins y adaptadores | política completa de migraciones y prueba de que nuevos adaptadores no fuerzan cambios independientes |
| 1 — Compilador | `LOCAL_VERTICAL_IMPLEMENTED` | DAG tipado, validación, resolución, orden topológico, plan, grafo y `workflow.lock.json` determinista | derivación universal desde la representación canónica y migración de rutas paralelas |
| 2 — Experiencia | `PARTIAL_LOCAL_ACCEPTANCE` | `environment check`, `project init`, validación explicable, plan y grafo | importar un cálculo existente hasta un WorkflowDefinition canónico sin reconstruir contratos internos |
| 3 — Ejecutor | `REMOTE_RUNTIME_DEBT_REMEDIATED / HUMAN_DECISION_PENDING` | job `781100`: paquete canónico, Hydra multinodo, padre → DM con SHA-256 → lectura confirmada → hijo; `781106`: matriz bruta PASS; `781111`/`781113`: señal y reanudación; `781115`: `srun` físico disjunto | aceptación humana formal de la transición |
| 4 — DAG adaptativo | `PARTIAL_NONCANONICAL_SLICES` | campañas, sweeps sintéticos y gates existen en rutas previas o ejemplos | integrar sweep/selection/fan-in y `converge_then_relax` en la representación y runtime canónicos |
| 5 — Portabilidad HPC | `PARTIAL_EVIDENCE` | launchers Hydra/srun, perfiles, probes de entorno y colocación | flujo completo de perfil aceptado, multinodo, continuación entre asignaciones y equivalencia de backends |
| 6 — Validación | `LOCAL_FOUNDATION_ACCEPTED` | catálogo SIESTA 5.4.2, contexto declarado, preflight y reglas versionadas | ampliar cobertura y campañas reales; resolver mediante ADR la separación entre severidad diagnóstica y estados contractuales |
| 7 — Resultados | `PARTIAL` | progreso, manifiestos, parsers e importadores de evidencia | consultas de linaje, tablas, comparación y exportación reproducible de extremo a extremo |
| 8 — Distribución | `PLANNED` | `pyproject.toml`, editable y configuración de wheel presentes | CI Linux, metadata completa, licencia, dependencias opcionales declaradas, sdist/wheel limpios, tutorial y validación externa |

Ningún estado `LOCAL_*` implica aceptación de Yoltla o validez científica.

## Clasificación de rutas actuales

| Ruta o artefacto | Clasificación | Política |
|---|---|---|
| `workflow validate/plan/graph/compile` → `workflow.lock.json` → `run prepare` → paquete → `AllocationController` | `CANONICAL` | única trayectoria de producción que puede cerrar Fase 3 |
| `remote controller-package` para campañas de controlador schema 1/2 | `COMPATIBILITY` | se conserva para paquetes existentes; no debe adquirir semántica distinta y debe converger mediante adaptadores |
| `campaign worker/progress/watch` dentro o alrededor del paquete | `COMPATIBILITY` | runtime/observación compartidos; su autoridad proviene del paquete verificado |
| `campaign create/validate/status` sobre definiciones previas | `COMPATIBILITY` | authoring previo; no sustituye WorkflowDefinition ni `workflow.lock.json` para nueva aceptación |
| `campaign simulate` y `examples run` | `TEST_ONLY` | usan ejecución sintética y no producen aceptación HPC |
| `remote package` | `TEST_ONLY` | genera preview inerte, nunca un paquete de producción aceptado |
| `remote m4-package` y paquetes smoke especializados | `EXPERIMENTAL` | cortes de aceptación; no son la ruta canónica general |
| `remote environment package/import` | `EXPERIMENTAL` | corte temprano de Fase 5 sujeto a revisión humana del perfil |
| directorios `*_SUPERSEDED_DO_NOT_USE` y paquetes históricos | `OBSOLETE_EVIDENCE` | se preservan para trazabilidad y no se ejecutan ni reescriben |

No se marca actualmente una CLI pública como `DEPRECATED` sin un ciclo de
compatibilidad documentado. Añadir funcionalidad a una ruta de compatibilidad
requiere demostrar que reutiliza contratos canónicos o registrar un ADR.

## Hitos de versión

Los hitos son cortes verticales, no equivalencias automáticas con fases:

| Versión objetivo | Corte utilizable | Gate mínimo |
|---|---|---|
| 0.2 alpha | fundamento de ejecución padre → DM → hijo | deuda runtime remediada; decisión humana formal pendiente |
| 0.3 alpha | campaña autónoma de convergencia y selección | Fase 3 cerrada y selección canónica con procedencia |
| 0.4 alpha | convergencia → relajación escalonada → validación → tabla | Fases 4 y 7 integradas para ese flujo |
| 0.5 alpha/beta | continuación y robustez HPC | evidencia multinodo, recuperación entre asignaciones y perfiles aceptados |
| 0.6 alpha | instalación para usuarios externos | gate de Fase 8 para wheel/sdist, CI, licencia y recorrido documentado |

Las versiones previas a 1.0 usan identificadores compatibles con PEP 440, por
ejemplo `0.3.0a1`, `0.3.0b1` o `0.3.0rc1`. No se cambia la versión por compilar
o por pasar únicamente pruebas locales.

## Escala y no objetivos

El objetivo inmediato es un workflow pequeño y verificable dentro de una
asignación Slurm, no un servicio multiusuario. No son objetivos actuales:

- sustituir SIESTAFLOW por AiiDA, Parsl o FireWorks;
- seleccionar ciencia automáticamente;
- ofrecer un daemon en login o un servicio externo obligatorio;
- instalar el stack científico del cluster;
- prometer escalabilidad no medida;
- mantener ediciones separadas de desarrollador y usuario;
- convertir los paquetes históricos en la nueva ruta por mera documentación.

Los límites de escala se consideran desconocidos fuera de la evidencia local y
HPC registrada. Cualquier afirmación multinodo o de rendimiento debe citar el
perfil, job, commit, paquete y resultados correspondientes.
