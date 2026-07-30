# PROMPT M3R2 — ACCOUNT-WIDE SLURM ASSOCIATION AND DEFAULT PARTITION RESOLUTION

## 0. Autopersistencia

Guarda íntegramente este prompt en:

```text
siestaflow/docs/governance/PROMPT_M3R2_ACCOUNT_WIDE_ASSOCIATION_AND_DEFAULT_PARTITION.md
```

Calcula su SHA-256 y registra ruta, fecha, tamaño y hash en:

```text
siestaflow/docs/context/CONTEXT_INVENTORY.md
```

Si falla:

```text
PROMPT_SELF_PERSISTENCE_FAILED
M3R2_NOT_STARTED
```

No hagas commits.

---

# 1. Hito autorizado

Ejecuta exclusivamente:

```text
M3R2_ACCOUNT_WIDE_SLURM_ASSOCIATION_AND_DEFAULT_PARTITION_RESOLUTION
```

Estado de entrada:

```text
M3R_LOCAL_PASS
M3G_ACCEPTED
M3R_LOCAL_PASS
M3_STATIC_V2_VERIFIED_ON_YOLTLA
LOGIN_PROBE_REAL_PASS
SCHEDULER_PROBE_NOT_GENERATED
NO_JOB_SUBMITTED
```

No repitas M0–M3R.

No ejecutes SIESTA, SLURM real, MPI real, SSH ni `sbatch`.

No continúes a M3B o M4.

---

# 2. Evidencia real vinculante

La evidencia real obtenida en Yoltla contiene:

```text
sacctmgr association:
vini||normal
```

Interpretación:

```yaml
account: vini
partition: null
qos: normal
association_scope: ALL_PARTITIONS
```

La salida real de `sinfo` identifica:

```text
q1h-20p*
```

La salida real de `scontrol show partition -o` identifica para `q1h-20p`:

```text
Default=YES
State=UP
AllowAccounts=ALL
AllowQos=ALL
MinNodes=1
MaxNodes=1
MaxTime=01:00:00
```

El parser actual descartó la asociación porque requería que la partición estuviera explícitamente presente.

No interpretes una partición vacía como falta de evidencia. Represéntala como asociación válida de alcance general.

---

# 3. Objetivo

Corregir de forma general el descubrimiento y resolución de perfiles SLURM cuando:

```text
sacctmgr entrega cuenta y QoS
pero no fija una partición
```

El flujo correcto debe ser:

```text
association account-wide
→ descubrir particiones visibles
→ analizar restricciones de cada partición
→ filtrar particiones compatibles
→ resolver la partición predeterminada si es única
→ generar perfil candidato con trazabilidad por campo
```

No hardcodees:

```text
vini
q1h-20p
normal
Yoltla
```

Estos valores sólo deben aparecer en fixtures de evidencia real o documentación de auditoría, nunca como defaults internos.

---

# 4. Modelo de asociaciones

Actualiza el modelo de asociación para soportar:

```text
EXPLICIT_PARTITION_ASSOCIATION
ACCOUNT_WIDE_ASSOCIATION
QOS_ONLY_ASSOCIATION
INCOMPLETE_ASSOCIATION
CONTRADICTORY_ASSOCIATION
```

Campos mínimos:

```text
account
partition
qos
scope
source_file
source_line
evidence_status
observed_at
```

Una fila:

```text
vini||normal
```

debe producir:

```yaml
account: vini
partition: null
qos: normal
scope: ACCOUNT_WIDE_ASSOCIATION
evidence_status: OBSERVED
```

No debe descartarse.

---

# 5. Parser de sacctmgr

Corrige:

```text
scripts/build_login_summary.py
```

y su fuente local correspondiente.

Debe aceptar correctamente:

```text
account|partition|qos
account||qos
account|partition|
account||
```

Reglas:

```text
account obligatorio
partition opcional
qos opcional
```

Una fila sin `account` es inválida.

Una fila con cuenta, pero sin partición, es una asociación account-wide.

Registra diagnósticos, no descartes silenciosamente.

---

# 6. Parser de sinfo

Implementa parsing estructurado de:

```text
partition
availability
time_limit
nodes
cpus_per_node
memory
default_marker
```

Debe reconocer el asterisco de partición predeterminada:

```text
q1h-20p*
```

y normalizar:

```yaml
name: q1h-20p
default: true
```

No conserves el asterisco como parte del nombre.

---

# 7. Parser de scontrol

Implementa parsing de las filas:

```text
PartitionName=...
AllowAccounts=...
AllowQos=...
Default=...
State=...
MinNodes=...
MaxNodes=...
MaxTime=...
```

Debe distinguir:

```text
ALL
lista explícita
N/A
valor ausente
```

No interpretes `AllowAccounts=ALL` como que cualquier cuenta inexistente es válida. Sólo significa que una cuenta ya observada no está bloqueada por esa partición.

---

# 8. Resolución de partición

Implementa una función genérica equivalente a:

```text
resolve_scheduler_candidates(
    associations,
    visible_partitions,
    partition_policies,
    resource_request,
)
```

Para una asociación account-wide:

1. toma la cuenta observada;
2. toma el QoS observado cuando exista;
3. considera únicamente particiones visibles;
4. exige `State=UP`;
5. verifica `AllowAccounts`;
6. verifica `AllowQos`;
7. verifica `MinNodes <= requested_nodes <= MaxNodes`;
8. verifica que el walltime solicitado no exceda `MaxTime`;
9. conserva toda la procedencia;
10. produce candidatos, no una elección oculta.

---

# 9. Política de selección automática

Puede seleccionarse automáticamente una partición únicamente cuando:

```text
existe exactamente una partición compatible marcada Default=YES
```

El resultado debe clasificarse como:

```text
DEFAULT_PARTITION_RESOLVED_FROM_REAL_EVIDENCE
```

Si existen varias particiones predeterminadas compatibles:

```text
SCHEDULER_PROBE_BLOCKED_MULTIPLE_DEFAULT_PARTITIONS
```

Si no existe ninguna predeterminada compatible y existe más de una candidata:

```text
SCHEDULER_PROBE_REQUIRES_HUMAN_SELECTION
```

Si no existe ninguna candidata:

```text
SCHEDULER_PROBE_BLOCKED_NO_COMPATIBLE_PARTITION
```

No selecciones la primera de una lista.

No prefieras una partición por orden alfabético.

No adoptes una partición del proyecto donante.

---

# 10. Selección humana respaldada por evidencia

Amplía `prepare_scheduler_probe.py` para aceptar opcionalmente:

```text
--account
--partition
--qos
```

Una selección humana sólo puede aceptarse si coincide con un candidato derivado de evidencia real.

Ejemplo conceptual:

```bash
python3 prepare_scheduler_probe.py \
  --login-evidence evidence/login_probe/summary.json \
  --account <observed-account> \
  --partition <compatible-observed-partition> \
  --qos <observed-qos> \
  --output generated/submit_environment_probe.slurm
```

Si el usuario introduce un valor no observado o incompatible:

```text
USER_SELECTION_NOT_SUPPORTED_BY_EVIDENCE
```

No permitas overrides arbitrarios.

Para el caso de una única partición predeterminada compatible, no debe ser obligatorio proporcionar selección manual.

---

# 11. Trazabilidad del perfil

El script generado debe incluir comentarios equivalentes a:

```text
account:
  value origin = sacctmgr association
  evidence status = OBSERVED

partition:
  value origin = sinfo default marker + scontrol policy
  evidence status = VERIFIED_BY_CROSS_SOURCE

qos:
  value origin = sacctmgr association
  evidence status = OBSERVED
```

Genera además:

```text
generated/scheduler_selection.json
```

Campos:

```text
account
partition
qos
nodes
ntasks
walltime
association_scope
candidate_partitions
selection_policy
source_files
evidence_status_by_field
```

---

# 12. Recursos del probe

El probe no científico puede solicitar:

```yaml
nodes: 1
ntasks: 1
cpus_per_task: 1
walltime: 00:02:00
```

Estos valores proceden de:

```text
M3_NON_SCIENTIFIC_MINIMAL_RESOURCE_POLICY
```

No son un perfil productivo SIESTA.

Antes de generar el script, verifica que la partición seleccionada admita:

```text
MinNodes <= 1 <= MaxNodes
MaxTime >= 00:02:00
```

---

# 13. Evidencia real como fixture

Incorpora una copia saneada de la evidencia real como fixture:

```text
tests/fixtures/m3r2/yoltla_account_wide_association/
```

Incluye:

```text
sacctmgr_assoc.txt
sinfo.txt
scontrol_partitions.txt
expected_summary.json
expected_selection.json
```

Marca:

```text
source: SANITIZED_REAL_REMOTE_EVIDENCE
credentials_present: false
scientific_calculation_performed: false
```

No incluyas rutas personales completas si no son necesarias.

---

# 14. Pruebas obligatorias

Añade pruebas para:

```text
cuenta con partición explícita
cuenta con partición vacía
cuenta con QoS vacío
cuenta con partición y QoS vacíos
fila sin cuenta
una partición default compatible
múltiples defaults
ningún default
default incompatible
partición DOWN
AllowAccounts incompatible
AllowQos incompatible
MinNodes incompatible
MaxNodes incompatible
walltime incompatible
selección humana válida
selección humana no observada
```

Caso real obligatorio:

```text
association = vini||normal
default partition = q1h-20p
AllowAccounts = ALL
AllowQos = ALL
State = UP
MinNodes = 1
MaxNodes = 1
```

Resultado esperado:

```text
account = vini
partition = q1h-20p
qos = normal
selection_policy = UNIQUE_COMPATIBLE_DEFAULT_PARTITION
```

Estos valores deben existir sólo dentro del fixture real saneado y de la documentación de evidencia.

---

# 15. Runtime test

Ejecuta localmente con stubs:

```text
parse real sanitized evidence
→ resolve candidates
→ select unique default
→ generate SLURM
→ validate Bash
→ validate embedded Python
→ execute generated script with SLURM stubs
→ produce scheduler summary
```

Resultado requerido:

```text
ACCOUNT_WIDE_ASSOCIATION_RUNTIME_PASS
DEFAULT_PARTITION_RESOLUTION_RUNTIME_PASS
GENERATED_SLURM_RUNTIME_PASS
```

---

# 16. Compatibilidad

Mantén compatibilidad con:

```text
asociación con partición explícita
asociación única anterior
selección humana respaldada
fixtures M3 y M3R
```

No rompas el comportamiento seguro:

```text
ambigüedad no resuelta → BLOCKED
ausencia de evidencia → BLOCKED
```

---

# 17. Paquete V3

Regenera:

```text
remote_validation/M3_YOLTLA_ENVIRONMENT_PROBE/
```

Declara:

```text
package_revision: 3
reproducibility_epoch: M3_STATIC_V3
supersedes: M3_STATIC_V2
```

Actualiza:

```text
probe_manifest.json
probe_manifest.sha256
checksums.sha256
README_RUN.md
EXACT_COMMANDS.md
PROBE_CHECKLIST.md
```

Genera:

```text
M3_YOLTLA_ENVIRONMENT_PROBE_V3_UPLOAD.zip
```

No incluyas evidencia generada localmente dentro del paquete distribuible.

No incluyas FDF, geometrías ni pseudopotenciales.

---

# 18. Reutilización de evidencia de login

La evidencia real de login V2 ya obtenida es válida.

Diseña V3 para permitir una de estas dos opciones seguras:

```text
A. volver a ejecutar run_login_probe.sh en una carpeta V3 limpia;

B. importar explícitamente el bundle o summary V2 mediante un comando
   verificado que preserve hash, procedencia y revisión de origen.
```

Prioriza A por simplicidad operativa.

No copies manualmente archivos de `evidence/` entre revisiones.

---

# 19. Documentación

Actualiza:

```text
CHANGELOG.md
docs/operations/YOLTLA_RUNBOOK.md
docs/operations/REMOTE_VALIDATION_WORKFLOW.md
docs/user/TROUBLESHOOTING.md
docs/developer/TESTING.md
```

Genera:

```text
docs/validation/M3R2_REAL_EVIDENCE_ANALYSIS.md
docs/validation/M3R2_ASSOCIATION_RESOLUTION_DESIGN.md
docs/validation/M3R2_TEST_EVIDENCE.md
docs/validation/M3R2_LIMITATIONS.md
```

Documenta que V2:

```text
pasó validaciones locales
se ejecutó parcialmente en Yoltla
obtuvo correctamente evidencia de login
bloqueó de forma segura
no contemplaba asociaciones account-wide
no envió ningún trabajo
```

---

# 20. Regresiones

Ejecuta todas las pruebas:

```text
M0
M1
M2
M3
M3G
M3R
M3R2
```

Resultado:

```text
0 failed
0 errors
```

Verifica:

```text
context/ = 642/642 byte-idéntico
```

---

# 21. Criterios de aceptación

M3R2 sólo puede aprobarse si:

```text
PROMPT_SELF_PERSISTED
ACCOUNT_WIDE_ASSOCIATION_SUPPORTED
EMPTY_PARTITION_NOT_DISCARDED
SINFO_DEFAULT_PARTITION_PARSED
SCONTROL_PARTITION_POLICY_PARSED
UNIQUE_DEFAULT_RESOLUTION_PASS
HUMAN_SELECTION_EVIDENCE_BOUND
REAL_SANITIZED_FIXTURE_PASS
GENERATED_SLURM_RUNTIME_PASS
M3_REMOTE_PACKAGE_V3_READY
ALL_REGRESSIONS_PASS
CONTEXT_UNMODIFIED
NO_REMOTE_JOB_SUBMITTED
```

Si falla:

```text
M3R2_INCOMPLETE
M3_PACKAGE_V3_NOT_APPROVED
```

---

# 22. Informe final

Entrega:

```text
HITO: M3R2_ACCOUNT_WIDE_SLURM_ASSOCIATION_AND_DEFAULT_PARTITION_RESOLUTION
ESTADO:
PROMPT_PATH:
PROMPT_SHA256:
REAL_EVIDENCE:
ROOT_CAUSE:
ACCOUNT_ASSOCIATION:
ASSOCIATION_SCOPE:
VISIBLE_PARTITIONS:
DEFAULT_PARTITION:
PARTITION_POLICY:
RESOLUTION_ALGORITHM:
HUMAN_SELECTION:
FILES_CORRECTED:
PACKAGE_REVISION:
PACKAGE_SHA256:
RUNTIME_TEST:
PRUEBAS_M0:
PRUEBAS_M1:
PRUEBAS_M2:
PRUEBAS_M3:
PRUEBAS_M3G:
PRUEBAS_M3R:
PRUEBAS_M3R2:
PRUEBAS_FALLIDAS:
CONTEXTO:
REMOTE_JOB:
LIMITACIONES:
NEXT_USER_ACTION:
```

---

# 23. Restricciones

No:

```text
hardcodear Yoltla
hardcodear vini
hardcodear q1h-20p
hardcodear normal
editar evidencia real
editar scripts en Yoltla
enviar sbatch
ejecutar SIESTA
modificar FDF
modificar pseudopotenciales
usar valores del donante como evidencia
hacer commits
continuar a M3B
continuar a M4
```

---

# 24. STOP CONDITION

Finaliza exactamente con:

```text
PROMPT_SELF_PERSISTED
ACCOUNT_WIDE_ASSOCIATION_RESOLUTION_PASS
UNIQUE_DEFAULT_PARTITION_RESOLUTION_PASS
REAL_YOLTLA_FIXTURE_PASS
GENERATED_SLURM_RUNTIME_TEST_PASS
M3_REMOTE_PACKAGE_V3_READY
ALL_REGRESSIONS_PASS
REAL_REMOTE_SCHEDULER_PROBE_PENDING
M3R2_COMPLETE_WAITING_FOR_HUMAN_REVIEW
```

No ejecutes V3.

No hagas commits.

Espera revisión humana.


