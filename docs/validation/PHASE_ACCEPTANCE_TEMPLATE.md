# Plantilla de aceptación de fase

Copie esta plantilla a un expediente nuevo. No modifique expedientes históricos
para representar una nueva ejecución. Use `NOT_APPLICABLE` únicamente con una
justificación en `known_limitations` o junto al campo correspondiente.

```yaml
phase: "PHASE_N"
status: "DRAFT | LOCAL_PASS_REMOTE_PENDING | ACCEPTED | REJECTED"
source_commit: "FULL_GIT_SHA | NOT_APPLICABLE"
source_tree_dirty: "true | false | NOT_APPLICABLE"
release_candidate: "PEP_440_VERSION_OR_NOT_APPLICABLE"
local_tests:
  status: "PASS | FAIL | SKIPPED | BLOCKED_BY_EXTERNAL_CONTEXT"
  commands: []
  summary: ""
remote_tests:
  status: "PASS | FAIL | SKIPPED | BLOCKED_BY_EXTERNAL_CONTEXT"
  commands: []
  summary: ""
cluster: "CLUSTER_AND_PROFILE_ID | NOT_APPLICABLE"
job_ids: []
package_sha256: "SHA256 | NOT_APPLICABLE"
workflow_lock_sha256: "SHA256 | NOT_APPLICABLE"
run_lock_sha256: "SHA256 | NOT_APPLICABLE"
execution_profile_sha256: "SHA256 | NOT_APPLICABLE"
audit_status: "APPROVED_FOR_MERGE | CONDITIONALLY_APPROVED | REJECTED"
known_limitations: []
accepted_by: "HUMAN_NAME_OR_NOT_YET_ACCEPTED"
date: "YYYY-MM-DD"
```

## Evidencia adjunta

Enlace las salidas completas, manifiestos, hashes, versión de SIESTA, launcher,
perfil, job y reconciliación. Distinga evidencia local, WSL/Slurm y HPC remoto.
Los secretos, rutas personales y datos científicos sin autorización se
redactan o permanecen fuera del repositorio.

## Declaraciones obligatorias

- La aceptación técnica no implica validez científica.
- Un paquete sucio no es publicable.
- `accepted_by` identifica a la autoridad humana; Codex no se autoasigna ese
  campo.
- Una fase no pasa si su criterio depende de contexto externo no ejecutado.
- Fase 3 requiere el paquete canónico de `run prepare` y evidencia limpia en
  Yoltla; una ejecución WSL no la sustituye.
