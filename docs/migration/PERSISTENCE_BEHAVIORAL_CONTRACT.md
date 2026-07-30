# Contrato conductual de persistencia y recuperación

## Baseline observado

El donante demuestra snapshots JSON por `tmp + os.replace`, histories de estado, job id y configuración de convergencia. No demuestra locks, event store, CAS, fsync, esquema riguroso, migraciones ni verificación del checksum al reanudar. El MD5 escrito por `_save_state()` es decorativo: `resume()` acepta un hash incorrecto y `is_dirty=true`.

## Stores separados

| Store | Propósito | Mutabilidad |
|---|---|---|
| `STATE_STORE` | snapshot materializado de campaña/worker/tarea | reemplazo atómico versionado |
| `EVENT_STORE` | decisiones y transiciones ordenadas | append-only |
| `ARTIFACT_STORE` | manifest de inputs/outputs/reportes | contenido inmutable por hash |

El estado no sustituye eventos ni artefactos. Cada snapshot referencia `last_event_id`, schema version, campaign id, allocation id, task id/attempt, autorización y hashes relevantes.

## Estados y transiciones

Estados operativos y resultados científicos se separan. Gates usan exclusivamente `PASS`, `REVIEW`, `FAIL`, `BLOCKED`; `REVIEW` nunca se convierte implícitamente en `PASS`. Las transiciones se validan mediante tabla explícita; no se permite el patrón donante donde `_advance_phase()` confía en el caller.

Cada commit lógico sigue: escribir artefactos → hash/manifest → append event → snapshot atómico. Si el proceso cae entre pasos, la reconciliación reproduce eventos o marca `BLOCKED`; nunca adelanta la tarea.

## Atomicidad e integridad

- temporal único en el mismo filesystem, flush/fsync de archivo, replace y fsync de directorio cuando esté soportado;
- SHA-256 o firma de contenido canónico, no MD5 decorativo;
- lectura valida schema, checksum, IDs y referencias antes de construir objetos;
- escrituras concurrentes usan lock o compare-and-swap con revision monotónica;
- secretos, credenciales y rutas locales sensibles no entran en eventos.

## Reanudación

Al iniciar dentro de una asignación, el worker carga y valida estado, reconcilia proceso/SLURM/artefactos, clasifica un intento ambiguo y decide una de: continuar tarea segura, iniciar el siguiente autorizado, detenerse para revisión o cerrar. Nunca vuelve a ejecutar automáticamente una tarea cuyo resultado podría existir sin comprobar idempotencia.

La pérdida de `squeue` no prueba éxito. Se contrastan exit record, `sacct` si está disponible, stdout/stderr, outputs SIESTA y eventos. Fallos de recursos no cambian parámetros físicos. Reinicios usan `RESTART_MANAGER` y una política SIESTA futura validada, no edición del primer input encontrado.

## Checkpoint y tiempo

Checkpoint después de cada transición y análisis; también ante señal de pre-timeout. `TIME_BUDGET` impide iniciar una tarea si `estimado + margen de checkpoint/salida` excede el tiempo restante. El worker sale con un estado explícito y recuperable.

## Caracterización asociada

`test_persistence_contract.py` verifica history y escritura atómica observada, demuestra checksum no aplicado, demuestra escritura real dentro de `audit_workspace(dry_run=True)` y captura el adapter moderno roto. Las pruebas futuras deben añadir crash injection, truncamiento, replay, concurrent writers, schema migration y reconciliación ambigua.

