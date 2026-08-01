# SIESTAFLOW 0.2 — estado de consolidación

Fecha de corte documental: 2026-08-01

Estado: `LOCAL_ACCEPTANCE_PASS / REMOTE_TWO_STAGE_ACCEPTANCE_PENDING`

Este estado es vinculante hasta que exista un expediente remoto canónico. La
arquitectura estable está en
[`SIESTAFLOW_BACKBONE.md`](SIESTAFLOW_BACKBONE.md), las dependencias en
[`SIESTAFLOW_PRODUCT_ROADMAP.md`](SIESTAFLOW_PRODUCT_ROADMAP.md) y los gates en
[`DEVELOPMENT_GOVERNANCE.md`](../developer/DEVELOPMENT_GOVERNANCE.md).

## Alcance consolidado

- Core Contracts 1.0 y adaptadores de compatibilidad.
- Compilador de DAG tipado y `workflow.lock.json` determinista.
- `run prepare` como puente local hacia `run.lock.json` y un paquete Slurm
  autocontenido.
- AllocationController dentro de la asignación, sin daemon en login.
- Launchers Hydra y `srun`, colocación explícita y tareas gate acotadas.
- Transferencia padre-hijo con procedencia y SHA-256.
- Persistencia, recuperación, shutdown controlado y observación de sólo lectura.
- Base local de validación SIESTA 5.4.2 y preflight del workflow.

## Validación local vigente

- Suite autocontenida del repositorio: `343 passed` el 2026-08-01.
- La aceptación WSL/Slurm registrada es integración local realista y permanece
  separada de Yoltla.
- `pyproject.toml` declara setuptools, Python >= 3.11, la CLI y package data.
- La versión permanece `0.2.0`; no se promueve por esta formalización.

Los conteos de pruebas en expedientes históricos describen su propio corte y no
son el estado vigente. Una nueva modificación debe volver a ejecutar los gates
en lugar de reutilizar este conteo.

## Aceptación remota pendiente

La Fase 3 sólo puede cerrarse con una ejecución limpia generada directamente
por la ruta canónica:

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
→ reconciliación final e importación de evidencia
```

La evidencia remota versionada no contiene actualmente el par
`workflow.lock.json`/`run.lock.json` de esa trayectoria. Existen paquetes,
probes y referencias históricas de Yoltla que informan compatibilidad y
defectos observados, pero no sustituyen este gate. No se declara cerrada la
Fase 3.

La matriz posterior también debe cubrir padre fallido, hash alterado, DM
ausente, interrupción recuperable y tareas independientes sin solapamiento de
recursos.

## Empaquetado y trazabilidad

La configuración actual permite derivar una distribución Python y paquetes HPC
de la misma base de código. La publicación para usuarios externos sigue siendo
trabajo de Fase 8: faltan CI versionada, licencia, metadata completa y
declaración formal de dependencias opcionales.

`run.lock.json` registra los hashes del workflow lock, perfil y campaña del
controlador. La preparación calcula además hashes del envelope de run y del ZIP.
Todavía faltan campos persistidos y uniformes para commit fuente, árbol sucio,
timestamp y hash final de paquete. Por política, un paquete formal debe provenir
de un árbol limpio; hasta implementar esos campos necesita un registro de build
externo verificable.

## Control de versiones

El repositorio sí tiene historial, identidad Git configurada y el tag
`v0.2.0`. El corte etiquetado corresponde al baseline de consolidación; los
commits posteriores no cambian por sí mismos la versión. No se crea tag ni se
hace push como parte de esta auditoría documental.

## Próximo gate

```text
Fase 3
→ paquete generado por run prepare
→ aceptación limpia padre → DM → hijo en Yoltla
```
