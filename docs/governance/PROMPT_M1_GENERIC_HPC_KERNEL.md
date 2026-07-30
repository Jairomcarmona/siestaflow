# PROMPT M1 — GENERIC HPC KERNEL

## Instrucción de autopersistencia

Antes de inspeccionar, crear o modificar cualquier otro archivo:

1. Crea el directorio:

```text
siestaflow/docs/governance/
```

2. Guarda **íntegramente y sin resumir este mismo prompt**, desde el encabezado:

```text
# PROMPT M1 — GENERIC HPC KERNEL
```

hasta la última condición de cierre, en:

```text
siestaflow/docs/governance/PROMPT_M1_GENERIC_HPC_KERNEL.md
```

3. Calcula el SHA-256 del archivo guardado.

4. Registra su ruta y hash en:

```text
siestaflow/docs/context/CONTEXT_INVENTORY.md
```

5. Si no puedes recuperar o guardar íntegramente el texto de este prompt, detente con:

```text
PROMPT_SELF_PERSISTENCE_FAILED
M1_NOT_STARTED
```

No es necesario que el usuario cree o copie manualmente ningún archivo.

---

## 1. Hito autorizado

Ejecuta exclusivamente:

```text
M1_GENERIC_HPC_KERNEL
```

M0 fue revisado y aprobado con condiciones.

Estado de entrada:

```text
M0_ACCEPTED
CONDITIONAL_GO_TO_M1
NO_SIESTA_IMPLEMENTATION_STARTED
```

No repitas M0 salvo que detectes una contradicción que bloquee la implementación.

---

## 2. Fuentes obligatorias

Usa como autoridad:

```text
siestaflow/docs/governance/PROMPT_M1_GENERIC_HPC_KERNEL.md
siestaflow/docs/context/
siestaflow/docs/migration/
context/scientific_governance/
context/donor/qe-postprocess-framework/
context/scientific_project_snapshot/
```

El contenido de `context/` es de sólo lectura.

No modifiques:

```text
context/
SIESTAFLOW_CONTEXT_v01.zip
```

No modifiques el repositorio donante ni el snapshot científico.

---

## 3. Objetivo de M1

Construir un núcleo HPC genérico, tipado, comprobable y sin dependencia directa de SIESTA.

El núcleo debe permitir posteriormente implementar:

```text
ONE_SBATCH_MANY_SIESTA_RUNS
```

pero en M1 sólo debe probarse con tareas simuladas y launchers falsos.

El resultado debe soportar:

```text
proyecto
→ workspace seguro
→ campaña genérica
→ tareas autorizadas
→ ejecución simulada
→ eventos
→ estado persistente
→ artefactos
→ compuertas
→ interrupción
→ reanudación
```

---

## 4. Alcance obligatorio

Implementa como mínimo:

```text
CORE DOMAIN MODELS
PROJECT_MANAGER
WORKSPACE_MANAGER
FILESYSTEM ABSTRACTION
DRY_RUN_FILESYSTEM
STATE_STORE
EVENT_STORE
ARTIFACT_STORE
AUTHORIZATION_ENGINE
GATE_ENGINE
PROCESS_LAUNCHER INTERFACE
LOCAL_FAKE_LAUNCHER
SLURM CLIENT INTERFACE
FAKE_SLURM_CLIENT
TIME_BUDGET
FAILURE_CLASSIFIER
BASIC CAMPAIGN PLANNER
```

No implementes archivos vacíos únicamente para cumplir nombres.

Cada módulo creado debe tener:

* responsabilidad definida;
* API mínima tipada;
* pruebas;
* manejo de errores;
* documentación breve;
* relación trazable con M0.

---

## 5. Modelo de dominio mínimo

Define modelos tipados equivalentes a:

```text
ProjectManifest
WorkspaceRecord
CampaignManifest
CampaignState
TaskSpec
TaskAttempt
TaskResult
AuthorizationEnvelope
GateDecision
AllocationContext
ArtifactRecord
EventRecord
FailureRecord
RuntimeEstimate
```

Estados de tarea:

```text
PLANNED
PREPARED
RUNNING
COMPLETED
REVIEW
FAILED
BLOCKED
INTERRUPTED
SKIPPED
```

Decisiones científicas u operativas:

```text
PASS
REVIEW
FAIL
BLOCKED
```

No representes estas decisiones mediante booleanos.

---

## 6. Restricciones obligatorias derivadas de M0

### 6.1 `squeue` vacío no significa éxito

Está prohibida cualquier lógica equivalente a:

```python
if job_not_in_squeue:
    status = "COMPLETED"
```

La ausencia de un trabajo en `squeue` debe clasificarse inicialmente como:

```text
TERMINAL_STATE_REQUIRES_EVIDENCE
```

La resolución futura debe considerar:

```text
sacct
exit code
sentinel de terminación
estado persistido
artefactos esperados
```

En Fake SLURM deben probarse al menos:

```text
COMPLETED
FAILED
CANCELLED
TIMEOUT
NODE_FAIL
UNKNOWN
```

### 6.2 Prevenir escape de rutas

Todo identificador utilizado para crear rutas debe rechazar:

```text
../
..\
rutas absolutas
letras de unidad
separadores incrustados
caracteres de control
componentes vacíos peligrosos
```

Después de resolver una ruta, comprueba que permanezca dentro del workspace autorizado.

Incluye pruebas explícitas de path traversal para Windows y POSIX.

### 6.3 No portar el adaptador moderno roto

El adaptador moderno identificado como defectuoso en el donante debe tratarse como:

```text
REWRITE
```

No copies su implementación.

Usa exclusivamente los contratos y pruebas de comportamiento derivados de M0.

### 6.4 Verificar procedencia de imports

Las pruebas deben comprobar que el paquete importado pertenece al checkout actual.

Añade una prueba que valide que:

```python
siestaflow.__file__
```

se encuentra dentro de la raíz esperada del proyecto.

La prueba debe fallar si importa:

* otra copia;
* una instalación global;
* un checkout anterior;
* una instalación editable ajena.

### 6.5 Mantener SIESTA fuera de M1

No implementes:

```text
FDF parser productivo
FDF variant generator científico
SIESTA output parser
SIESTA launcher
pseudopotential staging
Mesh.Cutoff sweep
k-grid sweep
DFT+U
spin
relajación
DOS
PDOS
counterpoise
```

Puedes usar nombres genéricos de motor o tareas simuladas, pero no lógica científica SIESTA.

---

## 7. Sistema de archivos

Define una interfaz explícita, por ejemplo:

```python
class FileSystem:
    def mkdir(...)
    def write_text(...)
    def read_text(...)
    def copy(...)
    def remove(...)
    def exists(...)
    def atomic_write_json(...)
```

Implementaciones mínimas:

```text
RealFileSystem
DryRunFileSystem
```

`DryRunFileSystem` debe:

* registrar operaciones;
* no modificar el disco;
* no crear directorios;
* no copiar;
* no borrar;
* permitir inspeccionar el plan.

No uses monkey-patching global como garantía de dry-run.

Incluye una prueba que compare hashes o inventario del directorio antes y después del dry-run.

---

## 8. Workspace

El workspace debe:

* usar identificadores sanitizados;
* crear rutas deterministas;
* impedir sobrescritura;
* separar campañas, tareas e intentos;
* soportar `attempt_001`, `attempt_002`, etc.;
* preservar resultados anteriores;
* registrar manifiestos;
* utilizar escritura atómica.

Estructura conceptual:

```text
workspace/
└── campaigns/
    └── <campaign_id>/
        ├── campaign.json
        ├── authorization.json
        ├── state.json
        ├── events.jsonl
        ├── artifacts.jsonl
        └── tasks/
            └── <task_id>/
                └── attempt_001/
```

No uses nombres proporcionados directamente por el usuario sin validación.

---

## 9. Persistencia

### Estado

Guardar mediante:

```text
archivo temporal
→ escritura
→ flush
→ fsync
→ atomic rename
```

### Eventos

`events.jsonl` debe ser append-only.

Cada evento debe incluir como mínimo:

```text
timestamp
campaign_id
task_id
attempt_id
event_type
previous_state
new_state
message
metadata
```

### Reanudación

Reglas mínimas:

* una tarea `COMPLETED` no se repite;
* una tarea encontrada como `RUNNING` después de reinicio pasa a `INTERRUPTED`;
* los outputs anteriores no se sobrescriben;
* un nuevo intento obtiene un ID nuevo;
* el estado reconstruido debe coincidir con los eventos persistidos;
* un archivo de estado corrupto debe detectarse y no ignorarse silenciosamente.

---

## 10. Autorización

Implementa una autorización inmutable y con hash.

Debe definir:

```text
allowed_task_types
allowed_system_ids o generic_targets
forbidden_operations
stop_on_review
issued_by
authorization_id
```

Una tarea no autorizada debe ser rechazada antes de preparar el workspace o ejecutar el launcher.

Prueba:

```text
AUTHORIZED_TASK → puede prepararse
UNAUTHORIZED_TASK → BLOCKED, cero efectos laterales
STALE_AUTHORIZATION → BLOCKED
HASH_MISMATCH → BLOCKED
```

---

## 11. Compuertas

Implementa:

```text
PASS
REVIEW
FAIL
BLOCKED
```

Reglas:

* `REVIEW` detiene la campaña;
* `REVIEW` nunca se convierte automáticamente en `PASS`;
* `FAIL` detiene;
* `BLOCKED` no ejecuta;
* sólo `PASS` permite avanzar;
* una compuerta debe registrar evidencia y razón.

No incluyas todavía criterios científicos SIESTA.

Usa criterios genéricos simulados.

---

## 12. Launchers

Define:

```text
ProcessLauncher
LocalFakeLauncher
```

`LocalFakeLauncher` debe poder simular:

```text
success
failure
timeout
cancelled
truncated_output
unknown_warning
interruption
```

No implementes aún:

```text
SrunLauncher
MpiexecHydraLauncher
MpirunLauncher
```

Puedes conservar sus interfaces previstas en documentación, pero no crear implementaciones falsas que aparenten estar validadas.

No parches globalmente `subprocess`.

---

## 13. Fake SLURM

Implementa una abstracción de cliente SLURM y una implementación falsa.

Debe simular:

```text
job submission identity
job state
allocation start
allocation end
remaining time
terminal states
signal before timeout
accounting evidence
```

No llames a:

```text
sbatch
squeue
sacct
scontrol
scancel
```

reales.

Prueba que un trabajo desaparecido de la cola no se marque como éxito sin evidencia terminal.

---

## 14. Tiempo restante

Implementa un `TimeBudget` genérico.

Regla:

```text
estimated_runtime × safety_factor
+ shutdown_margin
+ checkpoint_margin
< remaining_seconds
```

Valores iniciales configurables:

```yaml
safety_factor: 1.5
shutdown_margin_seconds: 1800
checkpoint_margin_seconds: 300
```

Cuando el runtime sea desconocido:

```text
UNKNOWN_RUNTIME
```

No inventes una estimación.

La política debe rechazar iniciar una segunda tarea salvo que exista una duración estática autorizada para la simulación.

---

## 15. Clasificación de fallos

Tipos mínimos:

```text
SUCCESS
INPUT_ERROR
PROCESS_FAILURE
TIMEOUT
OUT_OF_MEMORY
NODE_FAILURE
CANCELLED
INTERRUPTED
TRUNCATED_OUTPUT
UNKNOWN_WARNING
UNKNOWN_FAILURE
```

No cambies automáticamente parámetros de una tarea después de un fallo.

La recuperación debe limitarse a:

* registrar;
* preservar artefactos;
* marcar estado;
* permitir un nuevo intento sólo si la política lo autoriza.

---

## 16. Campaña simulada de aceptación

Implementa una campaña genérica de prueba:

```text
SIMULATED_CAMPAIGN_001
```

Debe contener tres tareas:

```text
TASK_001
TASK_002
TASK_003
```

Todas dentro de una asignación falsa común.

Prueba:

```text
un allocation_id
tres tareas secuenciales
tres workspaces
tres intentos
tres resultados
ninguna nueva asignación
eventos consistentes
estado final consistente
```

Añade escenarios separados:

1. las tres tareas terminan;
2. `TASK_002` produce `REVIEW`;
3. `TASK_002` falla;
4. queda poco tiempo antes de `TASK_003`;
5. interrupción durante `TASK_002` y reanudación;
6. autorización no permite `TASK_003`;
7. warning desconocido detiene la campaña.

---

## 17. Estructura permitida

Puedes crear una estructura similar a:

```text
siestaflow/
├── pyproject.toml
├── README.md
├── src/
│   └── siestaflow/
│       ├── core/
│       ├── project/
│       ├── filesystem/
│       ├── workspace/
│       ├── campaign/
│       ├── hpc/
│       ├── storage/
│       ├── recovery/
│       └── reporting/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── characterization/
│   └── smoke/
└── docs/
    ├── governance/
    ├── context/
    ├── migration/
    └── design/
```

No crees módulos vacíos que no sean necesarios para M1.

---

## 18. Documentación requerida

Crea o actualiza:

```text
siestaflow/docs/design/M1_GENERIC_HPC_KERNEL_ARCHITECTURE.md
siestaflow/docs/design/M1_DOMAIN_MODEL.md
siestaflow/docs/design/M1_STATE_MACHINE.md
siestaflow/docs/design/M1_SECURITY_AND_PATH_SAFETY.md
siestaflow/docs/design/M1_TEST_EVIDENCE.md
siestaflow/docs/design/M1_LIMITATIONS.md
```

Incluye trazabilidad hacia:

```text
siestaflow/docs/migration/
```

Documenta claramente qué comportamiento fue:

```text
PORT
REFACTOR
REWRITE
NEW_IMPLEMENTATION
```

---

## 19. Pruebas obligatorias

Ejecuta:

* pruebas unitarias del núcleo nuevo;
* pruebas de path traversal;
* pruebas de import provenance;
* pruebas de escritura atómica;
* pruebas de reconstrucción de estado;
* pruebas de autorización;
* pruebas de compuertas;
* pruebas de Fake SLURM;
* pruebas de TimeBudget;
* pruebas de campaña simulada;
* pruebas de dry-run sin efectos;
* pruebas de reanudación;
* smoke test completo de M1.

Ejecuta también las pruebas de caracterización M0 para comprobar que no se dañó la evidencia previa.

No es obligatorio volver a ejecutar todas las pruebas internas del donante salvo que el nuevo trabajo dependa de ellas directamente.

---

## 20. Criterios de aceptación

M1 sólo puede declararse aprobado si:

```text
PROMPT_SELF_PERSISTED
PATH_TRAVERSAL_BLOCKED
IMPORT_PROVENANCE_VERIFIED
DRY_RUN_ZERO_SIDE_EFFECTS
ATOMIC_STATE_WRITE_PASS
APPEND_ONLY_EVENTS_PASS
AUTHORIZATION_ENFORCED
REVIEW_STOPS_CAMPAIGN
EMPTY_SQUEUE_NOT_SUCCESS
FAKE_SLURM_PASS
TIME_BUDGET_PASS
INTERRUPTION_RESUME_PASS
NO_DUPLICATE_COMPLETED_TASKS
SIMULATED_ONE_ALLOCATION_THREE_TASKS_PASS
NO_SIESTA_IMPLEMENTATION_PRESENT
```

Si alguno falla, usa:

```text
M1_INCOMPLETE
```

No reduzcas pruebas para obtener un estado aprobado.

---

## 21. Restricciones absolutas

No debes:

* modificar `context/`;
* modificar el ZIP;
* modificar el donante;
* modificar el snapshot científico;
* ejecutar SIESTA;
* ejecutar SLURM real;
* usar SSH;
* implementar SIESTA;
* implementar FDF;
* iniciar campañas científicas;
* generar geometrías;
* modificar pseudopotenciales;
* hacer commits;
* borrar evidencia de M0;
* continuar a M2.

---

## 22. Informe final

Entrega:

```text
HITO: M1_GENERIC_HPC_KERNEL
ESTADO:
PROMPT_PATH:
PROMPT_SHA256:
ARCHIVOS_CREADOS:
ARCHIVOS_MODIFICADOS:
COMPONENTES_PORT:
COMPONENTES_REFACTOR:
COMPONENTES_REWRITE:
COMPONENTES_NUEVOS:
PRUEBAS_EJECUTADAS:
PRUEBAS_APROBADAS:
PRUEBAS_FALLIDAS:
DRY_RUN_EFFECTS:
PATH_SAFETY:
IMPORT_PROVENANCE:
PERSISTENCIA:
FAKE_SLURM:
CAMPAÑA_SIMULADA:
LIMITACIONES:
VALIDACIÓN_LOCAL:
VALIDACIÓN_REMOTA:
SIGUIENTE_HITO:
```

Distingue:

```text
OBSERVED
DOCUMENTED_ONLY
INFERRED
MISSING
CONTRADICTORY
```

---

## 23. STOP CONDITION

Detente cuando:

1. este prompt esté guardado íntegramente;
2. los módulos M1 estén implementados;
3. las pruebas M1 hayan sido ejecutadas;
4. la documentación requerida exista;
5. no exista implementación SIESTA;
6. no se haya iniciado M2.

El cierre debe terminar exactamente con:

```text
PROMPT_SELF_PERSISTED
GENERIC_HPC_KERNEL_PASS
M1_LOCAL_VALIDATION_COMPLETE
REMOTE_VALIDATION_NOT_RUN
NO_SIESTA_IMPLEMENTATION_STARTED
M1_COMPLETE_WAITING_FOR_HUMAN_REVIEW
```

No continúes a M2.
No hagas commits.
Espera revisión humana.
