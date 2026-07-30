# PROMPT M2 — FUNCTIONAL SIESTA VERTICAL SLICE

## 0. Autopersistencia obligatoria

Antes de modificar cualquier otro archivo:

1. Crea, si no existe:

```text
siestaflow/docs/governance/
```

2. Guarda íntegramente este prompt, desde el encabezado:

```text
# PROMPT M2 — FUNCTIONAL SIESTA VERTICAL SLICE
```

hasta la última condición de cierre, en:

```text
siestaflow/docs/governance/PROMPT_M2_FUNCTIONAL_SIESTA_VERTICAL_SLICE.md
```

3. Calcula su SHA-256.

4. Registra ruta, fecha y hash en:

```text
siestaflow/docs/context/CONTEXT_INVENTORY.md
```

5. Si no puedes guardar el prompt completo, detente con:

```text
PROMPT_SELF_PERSISTENCE_FAILED
M2_NOT_STARTED
```

El usuario no debe crear archivos manualmente.

---

# 1. Hito autorizado

Ejecuta exclusivamente:

```text
M2_FUNCTIONAL_SIESTA_VERTICAL_SLICE
```

Estado de entrada:

```text
M0_ACCEPTED
M1_ACCEPTED
GENERIC_HPC_KERNEL_PASS
NO_REAL_SIESTA_EXECUTION
```

No repitas M0 ni M1.

No hagas commits.

No continúes automáticamente a ejecución remota real.

---

# 2. Objetivo

Construye una rebanada vertical funcional de SIESTAFLOW que cubra:

```text
proyecto científico
→ descubrimiento de sistema
→ lectura preservadora del FDF
→ validación estática
→ verificación de pseudopotenciales
→ definición de campaña
→ autorización
→ generación de workspace
→ renderizado SLURM
→ ejecución SIESTA simulada
→ parsing de output
→ GateDecision
→ persistencia
→ reanudación
→ paquete remoto
→ importación local de resultados
→ informe auditable
```

El resultado debe permitir preparar de forma reproducible la primera campaña científica real:

```text
CAMPAIGN_01_M1_SANITY
```

También debe implementar y probar localmente la arquitectura persistente de:

```text
CAMPAIGN_02_M1_MESH_CONVERGENCE
```

pero debe mantenerla bloqueada hasta que exista:

```text
F1_REAL_RUN_COMPLETE
F2_OUTPUT_AUDIT_PASS
HUMAN_AUTHORIZATION_FOR_F3
```

No ejecutes SIESTA real.

---

# 3. Estado científico vinculante

Mantén:

```text
CURRENT_DFT_PROJECT_STATUS = SANITY_READY_PENDING_PREFLIGHT
HIGHEST_SUPPORTED_PHASE = F0_PARTIAL
CONFIRMED_SIESTA_RUNS = 0
REAL_SIESTA_OUTPUTS = 0
FIRST_REAL_CAMPAIGN = CAMPAIGN_01_M1_SANITY
FIRST_PERSISTENT_CAMPAIGN = CAMPAIGN_02_M1_MESH_CONVERGENCE
```

No promociones estos estados con fixtures sintéticos.

El sanity M1:

```text
M1_U0_FM.pilot.NO_PRODUCTION.fdf
```

es únicamente:

```text
lectura
pseudopotenciales
inicio SCF
terminación
output
diagnóstico técnico
```

No es una corrida productiva ni una selección de estado magnético.

---

# 4. Autoridades

Usa en este orden:

1. `PROMPT_M2_FUNCTIONAL_SIESTA_VERTICAL_SLICE.md`
2. Auditoría DFT del contexto.
3. Manual científico F0–F12.
4. Manual oficial SIESTA 5.4.2.
5. Código y pruebas de M1.
6. FDF y evidencia del snapshot científico.
7. JSON raw de palabras clave, sólo como corpus auxiliar.

El JSON conserva la clasificación:

```text
RAW_REFERENCE_CORPUS
NOT_AUTHORITATIVE
NOT_SAFE_FOR_AUTOMATIC_FDF_GENERATION
```

No copies automáticamente todas sus etiquetas a un registro operativo.

Todo `context/` es de sólo lectura.

---

# 5. Resultado funcional requerido

Al cerrar M2 debe ser posible ejecutar localmente, sin SIESTA real, un flujo equivalente a:

```bash
siestaflow project inspect <scientific-snapshot>

siestaflow fdf inspect <M1_U0_FM.fdf>

siestaflow campaign create \
  --template m1-sanity \
  --project <project-config>

siestaflow campaign validate <campaign>

siestaflow campaign simulate <campaign>

siestaflow remote package <campaign>

siestaflow remote results import <results-bundle>
```

Los nombres exactos pueden ajustarse, pero debe existir una interfaz operable y documentada.

No basta con clases aisladas sin flujo de extremo a extremo.

---

# 6. Arquitectura

Implementa SIESTA como adaptador sobre M1.

Estructura recomendada:

```text
src/siestaflow/
├── engines/
│   ├── base.py
│   └── siesta/
│       ├── models.py
│       ├── fdf_parser.py
│       ├── fdf_renderer.py
│       ├── fdf_registry.py
│       ├── fdf_variants.py
│       ├── input_validator.py
│       ├── pseudopotentials.py
│       ├── output_parser.py
│       ├── artifacts.py
│       ├── command.py
│       └── data/
├── campaigns/
│   └── siesta/
│       ├── sanity.py
│       └── mesh_convergence.py
├── hpc/
│   ├── slurm_renderer.py
│   └── persistent_worker.py
├── remote/
│   ├── packager.py
│   ├── preflight.py
│   ├── collector.py
│   └── importer.py
└── cli.py
```

No es obligatorio utilizar exactamente esos nombres.

No introduzcas lógica SIESTA dentro de los módulos genéricos de M1, salvo interfaces generales justificadas.

No crees módulos vacíos.

---

# 7. Contrato genérico de motor

Define o completa una interfaz equivalente a:

```python
class EngineAdapter:
    def inspect_input(...)
    def validate_input(...)
    def prepare_task(...)
    def build_command(...)
    def parse_output(...)
    def discover_artifacts(...)
    def classify_result(...)
```

Implementa:

```text
SiestaEngineAdapter
SyntheticSiestaLauncher
```

No implementes todavía un lanzador real específico de Yoltla.

El comando SIESTA debe representarse mediante configuración, no hardcodearse:

```yaml
engine:
  executable: null
  launcher:
    type: null
    command_template: null
```

---

# 8. Parser FDF funcional y preservador

Implementa un parser capaz de trabajar con los FDF reales del snapshot.

Debe reconocer y preservar:

```text
comentarios
líneas vacías
orden
capitalización
etiquetas escalares
valores
unidades
%block
%endblock
%include
redirecciones
contenido desconocido
finales de línea
```

Debe usar tokenización o máquina de estados. Las regex pueden ser auxiliares, no la arquitectura completa.

Modelos mínimos:

```text
FDFDocument
FDFNode
FDFScalar
FDFBlock
FDFComment
FDFBlankLine
FDFInclude
FDFUnknown
SourceSpan
ParseDiagnostic
```

Requisitos:

* no-op round-trip preservador;
* contenido desconocido preservado;
* bloques no cerrados detectados;
* `%endblock` incorrecto detectado;
* duplicados reportados;
* `%include` preservado;
* ninguna ruta externa abierta sin política;
* no asumir defaults;
* no corregir silenciosamente.

Todos los `.fdf`, `.fdf.NO_RUN` y `.fdf.template` del snapshot deben parsearse o recibir un diagnóstico controlado, nunca provocar un crash no clasificado.

---

# 9. Registro operativo de etiquetas

Genera:

```text
src/siestaflow/engines/siesta/data/supported_fdf_registry_5.4.2.json
```

Debe contener sólo las etiquetas y bloques necesarios para:

```text
los FDF existentes
M1_U0_FM sanity
Mesh.Cutoff
kgrid.MonkhorstPack
estructura atómica
especies
carga
spin
SCF
tipo de corrida
pasos geométricos
```

Cada entrada debe registrar:

```text
canonical_name
kind
value_type
unit_policy
repeat_policy
mutable_status
scientific_scope
evidence_class
manual_reference
notes
```

Estados:

```text
PARSED_ONLY
VALIDATED_READ_ONLY
MUTABLE_TECHNICAL
SCIENTIFICALLY_GOVERNED
PASSTHROUGH_UNKNOWN
```

`Mesh.Cutoff` y el bloque k-grid sólo pueden ser mutables si su sintaxis fue verificada contra el manual oficial.

Carga, spin, U, XC, base PAO, geometría y relajación deben permanecer científicamente gobernados o de sólo lectura.

---

# 10. Auditoría real de los FDF del snapshot

Ejecuta el parser y validador sobre:

```text
todos los .fdf
todos los .fdf.NO_RUN
todos los .fdf.template
```

Genera:

```text
siestaflow/docs/validation/M2_SNAPSHOT_FDF_AUDIT.md
siestaflow/docs/validation/M2_SNAPSHOT_FDF_AUDIT.json
```

Por archivo registra:

```text
ruta
hash
tipo
system_id
parse_status
validation_status
etiquetas
bloques
includes
desconocidos
duplicados
diagnósticos
execution_claim
```

Clasificaciones:

```text
REAL_FDF
NO_RUN_REVIEW_ARTIFACT
TEMPLATE
INVALID
UNKNOWN
```

El archivo sanity no puede superar:

```text
EXECUTION_READY_PENDING_PREFLIGHT
```

---

# 11. Validador estático

Implementa validación estructural funcional.

Debe verificar:

```text
NumberOfAtoms contra coordenadas
NumberOfSpecies contra ChemicalSpeciesLabel
índices de especies
cobertura de pseudopotenciales
bloques obligatorios
duplicados
bloques mal cerrados
includes
carga declarada
spin declarado
MD.Steps
tipo de corrida
presencia de geometría
parámetros bloqueados
```

Resultados:

```text
PASS
REVIEW
FAIL
BLOCKED
```

Ejemplos:

```text
pseudo ausente → BLOCKED
número de átomos incoherente → FAIL
etiqueta desconocida preservada → REVIEW
input sanity coherente → PASS técnico
```

No interpretes científicamente energía, U, spin o magnetismo.

---

# 12. Pseudopotenciales

Implementa un manifiesto content-addressed:

```text
PseudopotentialManifest
PseudopotentialEntry
PseudopotentialVerificationResult
```

Debe soportar:

```text
species
filename
format
sha256
source
xc_family
relativity
valence_metadata
distribution_status
location_status
```

Debe verificar:

```text
cobertura de especies
existencia cuando exista ruta
hash
duplicados
faltantes
formato declarado
especie esperada
```

No descargues ni copies pseudopotenciales externos.

Los PSML auditados pero no empaquetados deben conservar:

```text
EXTERNAL_NOT_PACKAGED
```

El paquete remoto debe poder exigir que el usuario indique una ruta del clúster y verificar allí los hashes.

---

# 13. Generador funcional de variantes

Implementa variantes de:

```text
Mesh.Cutoff
kgrid.MonkhorstPack
```

Debe requerir:

```text
AuthorizationEnvelope
base FDF hash
allowed_parameter
allowed_values
```

Por variante produce:

```text
FDF
hash
diff textual
diff semántico
manifest
provenance
```

Regla obligatoria:

```text
una sola variable autorizada por serie
```

Abortar ante cualquier cambio no autorizado de:

```text
geometría
celda
átomos
especies
pseudos
carga
spin
U
XC
base PAO
MD.Steps
relajación
```

Valores de Mesh previstos:

```text
200 Ry
250 Ry
300 Ry
350 Ry
```

Valores k-grid previstos:

```text
2×2×1
3×3×1
4×4×1
```

La generación debe probarse localmente, pero la campaña Mesh debe permanecer bloqueada por F2.

---

# 14. Parser funcional de outputs

Implementa parser streaming tolerante a outputs parciales.

Estado:

```text
PROVISIONAL_UNTIL_REAL_OUTPUT_IMPORTED
```

Debe extraer cuando exista evidencia:

```text
versión
inicio
terminación normal
SCF iniciado
SCF convergido
iteraciones
energías reportadas
fuerzas
warnings
errores
átomos
especies
spin o magnetización
tiempo
artefactos mencionados
```

Clasificaciones:

```text
COMPLETED
SCF_NOT_CONVERGED
INPUT_ERROR
PSEUDOPOTENTIAL_ERROR
ENVIRONMENT_ERROR
NUMERICAL_FAILURE
OUT_OF_MEMORY
TIMEOUT
NODE_FAILURE
CANCELLED
TRUNCATED_OUTPUT
UNKNOWN_WARNING
UNKNOWN_FAILURE
```

Reglas:

* energía presente no implica éxito;
* output truncado no es `COMPLETED`;
* warning desconocido produce `REVIEW`;
* no inventar exit code;
* no inventar archivos;
* la ausencia de terminación normal requiere evidencia adicional;
* parsing técnico no equivale a interpretación científica.

---

# 15. Fixtures sintéticos

Crea:

```text
tests/fixtures/siesta/synthetic/
```

Incluye como mínimo:

```text
normal_completion.out
scf_not_converged.out
input_error.out
missing_pseudopotential.out
truncated_output.out
unknown_warning.out
environment_error.out
timeout.out
spin_polarized_completion.out
```

Cada fixture debe tener:

```text
<fixture>.expected.json
```

con:

```text
synthetic: true
expected_classification
expected_gate
expected_fields
forbidden_inferences
```

No presentes fixtures como outputs oficiales.

---

# 16. CAMPAIGN_01_M1_SANITY

Implementa una plantilla funcional de campaña:

```text
CAMPAIGN_01_M1_SANITY
```

Propiedades:

```yaml
mode: human_gate_after_task
persistent_allocation: false
planned_tasks: 1
stop_after_task: true
scientific_interpretation: forbidden
```

Debe usar el candidato real del snapshot.

La creación de la campaña debe:

1. localizar el FDF;
2. calcular hash;
3. validar estructura;
4. verificar manifiesto de pseudos;
5. generar autorización;
6. crear workspace;
7. renderizar script SLURM;
8. generar preflight;
9. generar colector de resultados;
10. generar manifiesto remoto.

No debe ejecutarla.

---

# 17. CAMPAIGN_02_M1_MESH_CONVERGENCE

Implementa la campaña funcional:

```text
CAMPAIGN_02_M1_MESH_CONVERGENCE
```

Propiedades:

```yaml
mode: adaptive_sequential
persistent_allocation: true
values_ry:
  - 200
  - 250
  - 300
  - 350
```

Dependencias obligatorias:

```text
F1_REAL_RUN_COMPLETE
F2_OUTPUT_AUDIT_PASS
HUMAN_AUTHORIZATION_FOR_F3
```

Mientras no existan:

```text
campaign_status = BLOCKED_BY_SCIENTIFIC_GATE
```

El software debe probar la campaña mediante fixtures sintéticos y Fake SLURM.

No debe generar una autorización real que permita ejecutarla en el clúster.

Puede generar:

```text
MESH_CAMPAIGN_PREVIEW_ONLY
```

---

# 18. Worker persistente funcional

Integra el worker M1 con SIESTA.

En simulación debe realizar:

```text
una asignación falsa
→ Mesh 200
→ parse
→ gate
→ checkpoint
→ Mesh 250
→ parse
→ gate
→ checkpoint
→ Mesh 300
→ parse
→ gate
→ checkpoint
→ Mesh 350
→ parse
→ gate final
```

Debe detenerse ante:

```text
REVIEW
FAIL
BLOCKED
warning desconocido
output truncado
tiempo insuficiente
señal
autorización inválida
```

Debe reanudarse sin repetir tareas `COMPLETED`.

Prueba:

```text
ONE_FAKE_ALLOCATION
FOUR_SIESTA_TASKS
NO_ADDITIONAL_SBATCH
FOUR_SEPARATE_WORKSPACES
ATOMIC_CHECKPOINT_AFTER_EACH_TASK
```

No confundas esta simulación con validación real.

---

# 19. Renderizador SLURM

Implementa un renderizador funcional y configurable.

Debe producir:

```text
submit_campaign.slurm
```

Debe soportar:

```text
job name
partition
account
QoS
nodes
ntasks
cpus-per-task
memory
walltime
signal
module commands
launcher command
worker command
stdout
stderr
```

El perfil Yoltla permanece:

```text
UNVERIFIED_FOR_SIESTA
```

Por tanto, los campos desconocidos deben quedar `null`, producir placeholders explícitos o bloquear renderizado ejecutable.

No copies automáticamente el perfil LAMMPS.

Se permiten dos estados:

```text
PREVIEW_WITH_UNVERIFIED_PROFILE
EXECUTABLE_AFTER_PROFILE_VERIFICATION
```

El paquete sanity debe ser `PREVIEW_WITH_UNVERIFIED_PROFILE` hasta disponer de datos reales de Yoltla.

---

# 20. Paquete remoto funcional

Genera para el sanity:

```text
remote_validation/
└── CAMPAIGN_01_M1_SANITY/
    ├── README_RUN.md
    ├── VALIDATION_CHECKLIST.md
    ├── validation_manifest.json
    ├── validation_manifest.sha256
    ├── campaign.yaml
    ├── authorization.json
    ├── cluster_profile.yaml
    ├── engine_profile.yaml
    ├── preflight.sh
    ├── submit_campaign.slurm
    ├── inspect_job.sh
    ├── collect_results.sh
    ├── expected_files.txt
    ├── inputs/
    ├── scripts/
    └── checksums.sha256
```

El paquete debe:

* ser reproducible;
* contener hashes;
* no incluir secretos;
* no incluir pseudos sin autorización;
* no asumir rutas remotas;
* detenerse si el preflight falla;
* no enviar `sbatch` automáticamente;
* permitir inspección humana.

`preflight.sh` debe verificar:

```text
bash
SLURM commands
launcher
SIESTA executable
versión
MPI
pseudos
hashes
espacio
permisos
rutas
manifiesto
```

Como aún faltan datos, debe terminar actualmente en:

```text
REMOTE_PREFLIGHT_REQUIRES_CONFIGURATION
```

No debe fingir `PASS`.

---

# 21. Importador de resultados

Implementa:

```text
siestaflow remote results import <bundle>
```

Debe:

1. verificar identidad de campaña;
2. verificar hashes;
3. verificar manifiesto;
4. detectar archivos faltantes;
5. detectar outputs truncados;
6. parsear output;
7. importar eventos;
8. importar artefactos;
9. actualizar estado;
10. generar informe;
11. preservar originales.

Estados:

```text
REMOTE_RESULTS_IMPORTED
REMOTE_RESULTS_REVIEW
REMOTE_RESULTS_INVALID
REMOTE_RESULTS_INCOMPLETE
```

Prueba con bundles sintéticos.

Un bundle sintético nunca debe promoververse a evidencia real.

---

# 22. CLI funcional

Implementa una CLI suficiente para el flujo vertical.

Comandos mínimos:

```text
siestaflow context status

siestaflow fdf inspect <path>

siestaflow input validate <path>

siestaflow pseudo verify <manifest>

siestaflow campaign create m1-sanity

siestaflow campaign create m1-mesh --preview

siestaflow campaign validate <campaign>

siestaflow campaign simulate <campaign>

siestaflow campaign status <campaign>

siestaflow remote package <campaign>

siestaflow remote results import <bundle>
```

Requisitos:

* códigos de salida consistentes;
* errores legibles;
* salida humana;
* opción JSON cuando sea razonable;
* no ejecutar SIESTA;
* no ejecutar `sbatch`;
* no usar SSH.

---

# 23. Dry-run

Todo comando que genere o modifique debe soportar:

```text
--dry-run
```

Dry-run debe:

```text
mostrar plan
mostrar archivos
mostrar comandos
mostrar hashes previstos
mostrar estados previstos
no modificar disco
no ejecutar procesos
```

Debe conservar:

```text
DRY_RUN_ZERO_SIDE_EFFECTS
```

---

# 24. Artefactos y reinicios

Cataloga:

```text
.DM
.XV
.CG
.HSX
.WFSX
.RHO
.DRHO
.STRUCT_OUT
.bands
.DOS
.PDOS
```

Registra:

```text
ruta
tipo
tamaño
hash
task_id
attempt_id
```

Política:

```text
automatic_reuse: false
default_compatibility: DENY
```

No reutilices reinicios en M2.

---

# 25. Pruebas obligatorias

Ejecuta todas las pruebas M0 y M1.

Añade pruebas M2 para:

## FDF

```text
round-trip preservador
comentarios
bloques
includes
desconocidos
duplicados
bloques mal formados
Windows y POSIX
todos los FDF del snapshot
```

## Variantes

```text
Mesh cambia una sola variable
k-grid cambia una sola variable
dos cambios fallan
cambio de geometría falla
cambio de carga falla
cambio no autorizado se bloquea
```

## Pseudopotenciales

```text
manifest correcto
faltante
hash incorrecto
especie faltante
duplicado
formato incorrecto
```

## Outputs

```text
normal
SCF no convergido
input error
pseudo error
truncado
warning desconocido
timeout
environment error
spin
```

## Campañas

```text
sanity se crea
sanity se detiene después de una tarea
Mesh está bloqueada sin F2
Mesh simula cuatro tareas con una asignación
review detiene
fallo detiene
tiempo insuficiente detiene
reanudación no repite completadas
```

## SLURM

```text
perfil incompleto bloquea paquete ejecutable
preview conserva nulls
no se hereda perfil LAMMPS
no aparece un segundo sbatch
```

## Remote

```text
paquete reproducible
hashes válidos
preflight incompleto no pasa
bundle válido importa
bundle alterado falla
bundle incompleto queda REVIEW
```

## CLI

Prueba el flujo completo mediante subprocess local.

## Contexto

Verifica que `context/` conserve 642/642 archivos y hashes.

---

# 26. Demostración funcional obligatoria

Ejecuta una demostración local completa en un directorio temporal:

```text
1. inspeccionar M1_U0_FM
2. validar input
3. crear CAMPAIGN_01_M1_SANITY
4. simular output normal
5. obtener PASS técnico
6. detener por HUMAN_GATE_AFTER_TASK
7. generar paquete remoto preview
8. crear bundle sintético de resultados
9. importar bundle
10. producir informe
```

Ejecuta otra demostración:

```text
1. crear CAMPAIGN_02_M1_MESH_CONVERGENCE
2. demostrar bloqueo científico real
3. usar autorización sintética sólo para tests
4. simular 200/250/300/350 Ry
5. una asignación
6. cuatro tareas
7. cuatro checkpoints
8. reanudación sin duplicados
9. gate final
```

Guarda evidencia en:

```text
siestaflow/docs/validation/M2_FUNCTIONAL_DEMONSTRATION.md
```

---

# 27. Documentación requerida

Evita documentación fragmentada innecesariamente.

Crea únicamente:

```text
siestaflow/docs/design/M2_FUNCTIONAL_ARCHITECTURE.md
siestaflow/docs/siesta/M2_FDF_AND_INPUT_CONTRACT.md
siestaflow/docs/siesta/M2_OUTPUT_AND_ARTIFACT_CONTRACT.md
siestaflow/docs/operations/M2_REMOTE_WORKFLOW.md
siestaflow/docs/validation/M2_SNAPSHOT_FDF_AUDIT.md
siestaflow/docs/validation/M2_SNAPSHOT_FDF_AUDIT.json
siestaflow/docs/validation/M2_TEST_EVIDENCE.md
siestaflow/docs/validation/M2_FUNCTIONAL_DEMONSTRATION.md
siestaflow/docs/validation/M2_LIMITATIONS.md
```

Actualiza:

```text
README.md
CHANGELOG.md si existe
CONTEXT_INVENTORY.md
```

No crees informes redundantes.

---

# 28. Criterios de aceptación

M2 sólo puede aprobarse si:

```text
PROMPT_SELF_PERSISTED
M0_REGRESSION_PASS
M1_REGRESSION_PASS
FUNCTIONAL_CLI_PASS
FDF_SNAPSHOT_PARSE_PASS
FDF_PRESERVATION_PASS
STATIC_INPUT_VALIDATION_PASS
PSEUDOPOTENTIAL_AUDITOR_PASS
SINGLE_VARIABLE_VARIANTS_PASS
SYNTHETIC_OUTPUT_PARSER_PASS
SANITY_CAMPAIGN_END_TO_END_PASS
SANITY_REMOTE_PACKAGE_GENERATED
MESH_BLOCKED_WITHOUT_F2
PERSISTENT_MESH_SIMULATION_PASS
ONE_ALLOCATION_FOUR_TASKS_PASS
REMOTE_IMPORT_PASS
DRY_RUN_ZERO_SIDE_EFFECTS
CONTEXT_UNMODIFIED
NO_REAL_SIESTA_EXECUTION
NO_REAL_SLURM_EXECUTION
NO_YOLTLA_ASSUMPTIONS
```

Si cualquier criterio falla:

```text
M2_INCOMPLETE
```

No reduzcas pruebas para aprobar.

---

# 29. Restricciones absolutas

No debes:

* modificar `context/`;
* modificar el ZIP;
* modificar el donante;
* modificar el snapshot;
* ejecutar SIESTA real;
* ejecutar SLURM real;
* ejecutar MPI real;
* usar SSH;
* enviar `sbatch`;
* descargar pseudopotenciales;
* modificar FDF científicos;
* crear geometrías;
* seleccionar U;
* seleccionar spin;
* interpretar energías;
* ejecutar Mesh real;
* activar reinicios automáticos;
* inventar configuración Yoltla;
* hacer commits;
* iniciar producción;
* continuar automáticamente a ejecución remota.

---

# 30. Informe final

Entrega:

```text
HITO: M2_FUNCTIONAL_SIESTA_VERTICAL_SLICE
ESTADO:
PROMPT_PATH:
PROMPT_SHA256:
ARQUITECTURA:
ARCHIVOS_CREADOS:
ARCHIVOS_MODIFICADOS:
CAMBIOS_EN_M1:
PARSER_FDF:
SNAPSHOT_FDF:
REGISTRO_FDF:
VALIDADOR:
PSEUDOPOTENCIALES:
VARIANTES:
OUTPUT_PARSER:
CAMPAIGN_01_SANITY:
CAMPAIGN_02_MESH:
WORKER_PERSISTENTE:
SLURM_RENDERER:
PAQUETE_REMOTO:
IMPORTADOR:
CLI:
DRY_RUN:
PRUEBAS_M0:
PRUEBAS_M1:
PRUEBAS_M2:
PRUEBAS_FALLIDAS:
DEMOSTRACIÓN_FUNCIONAL:
CONTEXTO:
LIMITACIONES:
VALIDACIÓN_LOCAL:
VALIDACIÓN_REAL_SIESTA:
VALIDACIÓN_REMOTA:
SIGUIENTE_ACCIÓN:
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

# 31. STOP CONDITION

Detente cuando:

1. este prompt esté autopersistido;
2. el flujo funcional completo exista;
3. el sanity pueda prepararse, simularse, empaquetarse e importarse;
4. Mesh pueda simularse persistentemente, pero permanezca bloqueada para ejecución real;
5. la CLI funcione;
6. las pruebas M0 y M1 sigan pasando;
7. las pruebas M2 pasen;
8. `context/` permanezca intacto;
9. no se haya ejecutado SIESTA;
10. no se haya ejecutado SLURM real.

El cierre debe terminar exactamente con:

```text
PROMPT_SELF_PERSISTED
FUNCTIONAL_SIESTA_VERTICAL_SLICE_PASS
SANITY_END_TO_END_LOCAL_PASS
PERSISTENT_MESH_SIMULATION_PASS
REMOTE_SANITY_PACKAGE_PREVIEW_READY
REAL_SIESTA_VALIDATION_PENDING
REMOTE_VALIDATION_NOT_RUN
M2_COMPLETE_WAITING_FOR_HUMAN_REVIEW
```

No hagas commits.
No ejecutes el paquete remoto.
No continúes automáticamente.
Espera revisión humana.
