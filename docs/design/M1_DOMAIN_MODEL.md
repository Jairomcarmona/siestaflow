# Modelo de dominio M1

## Modelos

| Modelo | Rol e invariantes principales |
|---|---|
| `ProjectManifest` | ID, nombre, schema y creación del proyecto |
| `WorkspaceRecord` | campaña/tarea/intento y ruta confinada |
| `CampaignManifest` | plan inmutable y tareas ordenadas |
| `CampaignState` | snapshot mutable versionado; estados, intentos, resultados y allocation |
| `TaskSpec` | tipo/target/comando genérico y runtime estático opcional |
| `TaskAttempt` | identidad de intento dentro de una asignación |
| `TaskResult` | evidencia del launcher, no decisión booleana |
| `AuthorizationEnvelope` | alcance, prohibiciones, vigencia y SHA-256 |
| `GateDecision` | PASS/REVIEW/FAIL/BLOCKED, razón y evidencia |
| `AllocationContext` | identidad y presupuesto de la asignación falsa |
| `ArtifactRecord` | ruta relativa, tamaño y SHA-256 |
| `EventRecord` | transición append-only con contexto mínimo obligatorio |
| `FailureRecord` | clase de fallo, razón y retryable explícito |
| `RuntimeEstimate` | duración opcional, fuente y autorización |

## Enumeraciones

`TaskState`: `PLANNED`, `PREPARED`, `RUNNING`, `COMPLETED`, `REVIEW`, `FAILED`, `BLOCKED`, `INTERRUPTED`, `SKIPPED`.

`DecisionStatus`: `PASS`, `REVIEW`, `FAIL`, `BLOCKED`. Nunca se representa con booleanos.

`FailureType`: `SUCCESS`, `INPUT_ERROR`, `PROCESS_FAILURE`, `TIMEOUT`, `OUT_OF_MEMORY`, `NODE_FAILURE`, `CANCELLED`, `INTERRUPTED`, `TRUNCATED_OUTPUT`, `UNKNOWN_WARNING`, `UNKNOWN_FAILURE`.

## Serialización

`primitive()` convierte dataclasses, enums, tuples y mappings a JSON determinista. `StateStore` envuelve el payload con versión y SHA-256 de JSON canónico. La carga reconstruye enums tipados y rechaza versión, sintaxis o hash inválidos.

## Decisiones de migración

- Los `properties/metadata` irrestrictos del dominio moderno donor se clasificaron REWRITE.
- El patrón de dataclass se implementó nuevo; no se copió el adapter moderno roto.
- Metadata permanece únicamente en bordes extensibles (`TaskSpec`, eventos), mientras identidad, estados, fallos, decisiones y tiempos tienen campos/enums explícitos.

