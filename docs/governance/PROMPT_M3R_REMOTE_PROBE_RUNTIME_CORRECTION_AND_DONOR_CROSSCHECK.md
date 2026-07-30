# PROMPT M3R — REMOTE PROBE RUNTIME CORRECTION AND ENGINEERING DONOR CROSS-CHECK

## 0. Autopersistencia obligatoria

Antes de modificar cualquier otro archivo:

1. Crea, si no existe:

```text
siestaflow/docs/governance/
```

2. Guarda íntegramente este prompt, desde:

```text
# PROMPT M3R — REMOTE PROBE RUNTIME CORRECTION AND ENGINEERING DONOR CROSS-CHECK
```

hasta la última condición de cierre, en:

```text
siestaflow/docs/governance/PROMPT_M3R_REMOTE_PROBE_RUNTIME_CORRECTION_AND_DONOR_CROSSCHECK.md
```

3. Calcula su SHA-256.

4. Registra:

```text
ruta
fecha UTC
tamaño
SHA-256
```

en:

```text
siestaflow/docs/context/CONTEXT_INVENTORY.md
```

5. Si no puedes guardar una copia íntegra, detente con:

```text
PROMPT_SELF_PERSISTENCE_FAILED
M3R_NOT_STARTED
```

No hagas commits.

---

# 1. Hito autorizado

Ejecuta exclusivamente:

```text
M3R_REMOTE_PROBE_RUNTIME_CORRECTION_AND_ENGINEERING_DONOR_CROSSCHECK
```

Estado de entrada:

```text
M0_ACCEPTED
M1_ACCEPTED
M2_ACCEPTED
M3_LOCAL_PASS
M3G_ACCEPTED
REMOTE_EVIDENCE_NOT_YET_COLLECTED
REMOTE_PACKAGE_V1_NOT_EXECUTED
```

No repitas M0, M1, M2, M3 o M3G.

No continúes a M3B.

No continúes a M4.

No ejecutes:

```text
SIESTA
MPI real
SLURM real
SSH
sbatch
srun real
mpiexec real
mpirun real
```

---

# 2. Objetivo

Corregir los defectos de ejecución detectados en el paquete:

```text
remote_validation/M3_YOLTLA_ENVIRONMENT_PROBE/
```

y demostrar que los scripts corregidos:

```text
compilan
→ se renderizan correctamente
→ se ejecutan con stubs controlados
→ generan evidencia válida
→ clasifican correctamente los estados SLURM
→ producen un paquete remoto V2 reproducible
```

También debes utilizar de manera puntual el proyecto sólido:

```text
qef-framework
o
qe-postprocess-framework
```

incluido en el contexto, exclusivamente como:

```text
ENGINEERING_DONOR
NOT_ARCHITECTURAL_AUTHORITY
NOT_SCIENTIFIC_AUTHORITY
NOT_COPY_SOURCE_WITHOUT_VALIDATION
```

---

# 3. Defectos confirmados

## 3.1 Defecto A — Python embebido inválido

Archivo:

```text
remote_validation/M3_YOLTLA_ENVIRONMENT_PROBE/inspect_probe_job.sh
```

Existe un heredoc Python cuya escritura de JSON quedó representada de forma equivalente a:

```python
write_text(json.dumps(data, sort_keys=True, indent=2) + '
')
```

Esto produce Python sintácticamente inválido.

Debe producir código válido, por ejemplo:

```python
write_text(
    json.dumps(data, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
```

La corrección debe realizarse en la fuente correspondiente, no únicamente en una copia generada.

---

## 3.2 Defecto B — escape incorrecto en script generado

Archivo:

```text
prepare_scheduler_probe.py
```

El generador construye:

```text
generated/submit_environment_probe.slurm
```

que contiene a su vez un heredoc Python.

El string exterior interpreta el salto de línea antes de escribir el código embebido. El resultado vuelve a quedar sintácticamente inválido.

La solución debe asegurar que el archivo renderizado contenga literalmente:

```python
+ "\n"
```

Puede resolverse mediante:

```python
+"\\n"
```

en el string generador, mediante una plantilla segura o mediante una estrategia equivalente.

No hagas una sustitución textual ciega.

Corrige la causa de renderizado y valida el artefacto final generado.

---

# 4. Principios de corrección

Las correcciones deben seguir:

```text
corregir la fuente
→ regenerar el artefacto
→ validar sintaxis
→ ejecutar con stubs
→ verificar resultados
```

Está prohibido:

```text
editar sólo el archivo generado
ocultar el fallo con try/except
ignorar el exit code
reducir pruebas
eliminar evidencia
declarar PASS sólo porque bash -n pasa
```

Los scripts generados son productos ejecutables y deben probarse como tales.

---

# 5. Engineering donor cross-check

Usa el repositorio:

```text
qef-framework
o
qe-postprocess-framework
```

incluido en el contexto exclusivamente como donante de ingeniería.

No asumas el nombre exacto ni una ruta fija. Localízalo dentro del contexto mediante inventario o búsqueda controlada.

No modifiques el donante.

No ejecutes comandos destructivos dentro del donante.

No conviertas el donante en dependencia de runtime.

---

## 5.1 Componentes que deben compararse

Para cada uno de los siguientes componentes SIESTAFLOW:

```text
prepare_scheduler_probe.py
inspect_probe_job.sh
verify_local_package.py
run_login_probe.sh
collect_probe_results.sh
scripts/collect_bundle.py
scripts/probe_common.sh
```

localiza, si existe, el componente funcionalmente equivalente en el donante relacionado con:

```text
renderizado SLURM
generación de deployment kits
validación de scripts
manejo de subprocess
captura de stdout/stderr
clasificación de estados terminales
reanudación
manifiestos y checksums
pruebas end-to-end
smoke tests
```

---

## 5.2 Clasificación obligatoria

Clasifica cada patrón del donante como:

```text
PORT
REFACTOR
REWRITE
DISCARD
NO_EQUIVALENT_FOUND
```

Definiciones:

```text
PORT:
  patrón genérico reutilizable con cambios mínimos

REFACTOR:
  patrón sólido pero acoplado a QE, LAMMPS, clúster o formato específico

REWRITE:
  contrato útil, implementación incompatible con SIESTAFLOW

DISCARD:
  patrón inseguro, obsoleto, roto o contrario a la gobernanza actual

NO_EQUIVALENT_FOUND:
  no existe un componente comparable
```

---

## 5.3 Información que debes registrar

Para cada comparación documenta:

```text
SIESTAFLOW_COMPONENT
DONOR_COMPONENT
DONOR_PATH
CLASSIFICATION
INPUT_CONTRACT
OUTPUT_CONTRACT
ERROR_HANDLING
EXIT_CODE_HANDLING
STDOUT_STDERR_CAPTURE
VALIDATION_STRATEGY
EXECUTED_TESTS
PATTERN_REUSED
PATTERN_REJECTED
ADAPTATION_REQUIRED
FINAL_DECISION
```

Genera:

```text
siestaflow/docs/validation/M3R_ENGINEERING_DONOR_CROSSCHECK.md
siestaflow/docs/validation/M3R_ENGINEERING_DONOR_CROSSCHECK.json
```

---

## 5.4 Restricciones del donante

No copies desde el donante:

```text
lógica específica de Quantum ESPRESSO
nombres de ejecutables QE
parsers QE
rutas de clúster
cuentas
particiones
QoS
supuestos LAMMPS
credenciales
nombres científicos
campañas concretas
manejo inseguro de squeue
adaptadores rotos conocidos
```

La autoridad para SIESTA sigue siendo:

```text
manual oficial SIESTA
contratos M1-M3G
adaptador SIESTA
evidencia local y remota
```

El donante sólo orienta decisiones de ingeniería.

---

# 6. Auditoría completa de scripts M3

Revisa al menos:

```text
run_login_probe.sh
inspect_probe_job.sh
collect_probe_results.sh
prepare_scheduler_probe.py
verify_local_package.py
submit_environment_probe.slurm
scripts/build_login_summary.py
scripts/collect_bundle.py
scripts/probe_common.sh
scripts/verify_pseudos.py
```

Busca:

```text
Python embebido en Bash
heredocs
comillas anidadas
escapes de saltos de línea
strings renderizados
scripts Bash construidos por Python
rutas inseguras
sobrescritura silenciosa
códigos de salida ignorados
stdout/stderr no preservados
squeue usado como evidencia terminal
sacct mal interpretado
JSON inválido
scripts que pasan sintaxis pero fallan en runtime
```

Clasifica cada hallazgo:

```text
CONFIRMED_RUNTIME_DEFECT
POTENTIAL_RUNTIME_DEFECT
SECURITY_DEFECT
PORTABILITY_DEFECT
OBSERVABILITY_DEFECT
STYLE_ONLY
NO_DEFECT
```

Corrige todos los casos salvo `STYLE_ONLY`.

Genera:

```text
siestaflow/docs/validation/M3R_RUNTIME_DEFECT_AUDIT.md
siestaflow/docs/validation/M3R_RUNTIME_DEFECT_AUDIT.json
```

---

# 7. Validador general de Python embebido

Implementa un validador reutilizable, por ejemplo:

```text
src/siestaflow/validation/embedded_code.py
```

y una entrada ejecutable en el paquete remoto:

```text
scripts/validate_embedded_python.py
```

Debe:

1. recibir uno o más archivos;
2. detectar heredocs Python, al menos:

```bash
<<'PY'
<<"PY"
<<PY
```

3. extraer el contenido del heredoc;
4. preservar información de archivo y líneas;
5. compilar mediante:

```python
compile(source, filename, "exec")
```

6. no ejecutar el código;
7. producir diagnóstico legible;
8. regresar código distinto de cero ante error;
9. soportar scripts `.sh` y `.slurm`;
10. detectar múltiples heredocs por archivo.

Salida exitosa:

```text
EMBEDDED_PYTHON_SYNTAX_VERIFIED
```

Salida de fallo:

```text
EMBEDDED_PYTHON_SYNTAX_ERROR
```

acompañada de:

```text
archivo
línea inicial
línea del error
mensaje
```

---

# 8. Validación estática de scripts

Implementa una validación central que compruebe:

## Python directo

```bash
python3 -m py_compile <todos los .py>
```

## Bash

```bash
bash -n <todos los .sh>
```

## SLURM/Bash

```bash
bash -n <todos los .slurm>
```

## Python embebido

```bash
python3 scripts/validate_embedded_python.py <scripts>
```

No declares un script válido sólo porque su extensión no sea `.py`.

---

# 9. Validación del script generado

Después de ejecutar:

```text
prepare_scheduler_probe.py
```

sobre evidencia controlada, valida automáticamente:

```bash
bash -n generated/submit_environment_probe.slurm

python3 scripts/validate_embedded_python.py \
  generated/submit_environment_probe.slurm
```

`prepare_scheduler_probe.py` debe fallar si el artefacto generado es inválido.

Estado de fallo:

```text
GENERATED_SCHEDULER_SCRIPT_INVALID
```

No debe conservar un archivo aparentemente ejecutable cuando la validación falle.

Puede:

```text
eliminarlo
o
renombrarlo con extensión .INVALID
```

pero debe documentar la decisión.

---

# 10. Prueba ejecutada del script SLURM generado

No basta con validar sintaxis.

Añade una prueba de integración que:

1. cree un directorio temporal;
2. genere evidencia de login sintética;
3. incluya una única asociación válida:

```text
account
partition
qos opcional
```

4. ejecute `prepare_scheduler_probe.py`;
5. genere `submit_environment_probe.slurm`;
6. prepare un entorno temporal con variables:

```text
SLURM_JOB_ID
SLURM_JOB_PARTITION
SLURM_JOB_ACCOUNT
SLURM_JOB_QOS
SLURM_NNODES
SLURM_NTASKS
SLURM_CPUS_PER_TASK
SLURM_JOB_END_TIME
```

7. proporcione stubs controlados para:

```text
module
srun
mpirun
mpiexec
mpiexec.hydra
hostname
df
```

8. ejecute realmente el script generado mediante Bash;
9. compruebe exit code cero;
10. compruebe que exista:

```text
evidence/scheduler_probe/summary.json
```

11. valide el JSON;
12. verifique:

```text
scientific_calculation_performed = false
signal_received = true
job_id no nulo
partition coincide
account coincide
```

No debe ejecutarse SIESTA.

No debe usarse SLURM real.

---

# 11. Prueba ejecutada de inspect_probe_job.sh

Añade pruebas que ejecuten realmente:

```text
inspect_probe_job.sh
```

con stubs de:

```text
squeue
sacct
```

Casos mínimos:

## Caso A — RUNNING

```text
squeue presente
sacct RUNNING
terminal_evidence = false
```

## Caso B — COMPLETED

```text
squeue vacío
sacct COMPLETED
ExitCode 0:0
terminal_evidence = true
state = COMPLETED
exit_code = 0:0
```

## Caso C — FAILED

```text
squeue vacío
sacct FAILED
ExitCode 1:0
terminal_evidence = true
state = FAILED
```

No debe promocionarse a éxito.

## Caso D — sin evidencia

```text
squeue vacío
sacct vacío
terminal_evidence = false
state = null
```

## Caso E — TIMEOUT

```text
state = TIMEOUT
terminal_evidence = true
```

## Caso F — NODE_FAIL

```text
state = NODE_FAIL
terminal_evidence = true
```

Verifica que:

```text
ausencia de squeue != éxito
```

---

# 12. Robustez de parsing de sacct

Revisa el parsing de:

```text
JobID
State
ExitCode
Elapsed
AllocTRES
MaxRSS
NodeList
Partition
Account
QOS
```

Debe manejar:

```text
filas del job principal
filas .batch
filas .extern
sufijo +
espacios
campos vacíos
estados compuestos
```

La selección del job principal debe ser explícita.

No tomes accidentalmente la fila `.batch`.

Añade fixtures para:

```text
COMPLETED
FAILED
CANCELLED
TIMEOUT
NODE_FAIL
OUT_OF_MEMORY
PREEMPTED
BOOT_FAIL
DEADLINE
```

Los estados desconocidos deben producir:

```text
terminal_evidence = false
review_required = true
```

salvo que exista una política explícita respaldada por documentación.

---

# 13. Verificador del paquete remoto

Amplía:

```text
verify_local_package.py
```

para verificar:

```text
checksums
probe manifest
probe manifest hash
ausencia de archivos científicos prohibidos
ausencia de secretos evidentes
sintaxis Python directa
sintaxis Bash
sintaxis SLURM
Python embebido
rutas relativas seguras
archivos requeridos
permisos mínimos razonables
```

No debe ejecutar:

```text
SIESTA
sbatch
srun
mpiexec
```

Salida exitosa:

```text
M3_PACKAGE_HASHES_VERIFIED
M3_PACKAGE_RUNTIME_SYNTAX_VERIFIED
M3_PACKAGE_STRUCTURE_VERIFIED
```

No debe afirmar:

```text
REMOTE_EXECUTION_PASS
```

porque aún no existe ejecución remota.

---

# 14. Validación de secretos

Revisa el contenido textual del paquete y bloquea patrones evidentes:

```text
PASSWORD=
TOKEN=
SECRET=
PRIVATE KEY
BEGIN OPENSSH PRIVATE KEY
AWS_SECRET_ACCESS_KEY
COOKIE=
CREDENTIAL=
```

Permite referencias documentales genéricas, pero no valores reales.

Genera un diagnóstico de archivo y línea.

---

# 15. Seguridad de rutas

Verifica en todos los scripts:

```text
paths absolutos cuando corresponda
rechazo de ../
rechazo de traversal en tar
rechazo de sobrescritura
directorios temporales únicos
resolución controlada de symlinks
```

Añade pruebas POSIX y, donde aplique al código local Python, pruebas con rutas tipo Windows.

No introduzcas incompatibilidad innecesaria con Yoltla Linux.

---

# 16. Bundle collector

Prueba realmente:

```text
scripts/collect_bundle.py
```

con evidencia sintética completa.

Debe generar:

```text
M3_YOLTLA_ENVIRONMENT_RESULTS_<timestamp>.tar.gz
```

Comprueba:

```text
estructura esperada
results_manifest.json
results_manifest.sha256
checksums.sha256
timestamps reproducibles cuando aplique
uid/gid normalizados
sin traversal
sin archivos externos
sin symlinks peligrosos
```

Añade casos:

```text
evidencia completa
stdout faltante
stderr faltante
summary faltante
pseudo verification faltante
bundle preexistente
```

---

# 17. Pseudopotential verifier

No cambies la política científica ni hashes auditados.

Prueba:

```text
Mn/O correctos
Mn faltante
O faltante
hash incorrecto
formato no PSML
dos candidatos con el mismo nombre
ruta inexistente
archivo ilegible
```

El script debe producir estados controlados:

```text
PSEUDOS_MN_O_HASH_VERIFIED
PSEUDOS_MN_O_MISSING
PSEUDOS_MN_O_HASH_MISMATCH
PSEUDOS_MN_O_REVIEW
```

No debe copiar ni modificar pseudos.

---

# 18. Package revision V2

Regenera íntegramente:

```text
siestaflow/remote_validation/M3_YOLTLA_ENVIRONMENT_PROBE/
```

No parches únicamente la carpeta remota ya transferida.

La nueva versión debe declarar:

```text
reproducibility_epoch: M3_STATIC_V2
package_revision: 2
supersedes: M3_STATIC_V1
```

Actualiza:

```text
probe_manifest.json
probe_manifest.sha256
checksums.sha256
expected_evidence.json si corresponde
README_RUN.md
EXACT_COMMANDS.md
PROBE_CHECKLIST.md
```

No incluyas:

```text
FDF
geometrías
pseudopotenciales
credenciales
comandos científicos
```

---

# 19. Instrucciones remotas V2

`EXACT_COMMANDS.md` debe incluir la secuencia exacta:

```bash
cd M3_YOLTLA_ENVIRONMENT_PROBE

python3 verify_local_package.py

chmod u+x \
  run_login_probe.sh \
  inspect_probe_job.sh \
  collect_probe_results.sh \
  scripts/*.sh \
  scripts/*.py

./run_login_probe.sh

python3 prepare_scheduler_probe.py \
  --login-evidence evidence/login_probe/summary.json \
  --output generated/submit_environment_probe.slurm

bash -n generated/submit_environment_probe.slurm

python3 scripts/validate_embedded_python.py \
  generated/submit_environment_probe.slurm

sed -n '1,240p' generated/submit_environment_probe.slurm
```

Después debe indicar explícitamente:

```text
DETENERSE PARA INSPECCIÓN HUMANA
```

Sólo tras revisión humana:

```bash
sbatch generated/submit_environment_probe.slurm \
  | tee evidence/scheduler_probe/sbatch_submission.txt
```

Después:

```bash
JOB_ID=$(awk '/Submitted batch job/{print $NF}' \
  evidence/scheduler_probe/sbatch_submission.txt)

./inspect_probe_job.sh "$JOB_ID"
```

Y repetir:

```bash
./inspect_probe_job.sh "$JOB_ID"
```

después de que el trabajo salga de `squeue`, hasta obtener evidencia terminal mediante `sacct`.

Finalmente:

```bash
export PSEUDO_ROOT='/ruta/absoluta/a/psml/auditados'

./collect_probe_results.sh \
  --pseudo-root "$PSEUDO_ROOT"
```

No incluyas comandos que ejecuten un FDF.

---

# 20. Documentación como código

Actualiza:

```text
README.md
CHANGELOG.md
docs/user/USER_MANUAL.md
docs/user/CLI_REFERENCE.md
docs/user/TROUBLESHOOTING.md
docs/operations/YOLTLA_RUNBOOK.md
docs/operations/REMOTE_VALIDATION_WORKFLOW.md
docs/developer/TESTING.md
```

Registra:

```text
causa del defecto
impacto
por qué los tests anteriores no lo detectaron
pruebas nuevas
revisión V2 del paquete
instrucción para descartar V1
```

No ocultes el defecto.

No presentes V1 como utilizable.

---

# 21. Pruebas obligatorias

Ejecuta todas las pruebas:

```text
M0
M1
M2
M3
M3G
M3R
```

Añade pruebas específicas para:

```text
Python directo válido
Bash válido
SLURM válido
Python embebido válido
Python embebido inválido detectado
script generado ejecutado con stubs
inspect job ejecutado con stubs
squeue vacío sin sacct no aceptado
COMPLETED 0:0 identificado
FAILED no promovido
TIMEOUT identificado
NODE_FAIL identificado
bundle generado
bundle incompleto bloqueado
secretos detectados
traversal detectado
pseudos verificados
paquete V2 reproducible
documentación consistente
```

Resultado requerido:

```text
0 FAILED
0 ERRORS
```

No reduzcas la suite anterior.

---

# 22. Contexto y trazabilidad

Verifica:

```text
context/ = 642/642 archivos byte-idénticos
```

No modifiques:

```text
context/
ZIP original
repositorio donante
snapshot científico
```

Registra el hash del nuevo paquete V2.

Si el paquete es una carpeta, genera además un manifiesto raíz verificable.

---

# 23. Demostración local obligatoria

Ejecuta una demostración en directorio temporal:

```text
generar paquete V2
→ verificar paquete
→ ejecutar login probe con stubs
→ construir summary
→ preparar script SLURM
→ validar Bash
→ validar Python embebido
→ ejecutar script generado con entorno SLURM simulado
→ generar scheduler summary
→ simular sacct COMPLETED
→ ejecutar inspect_probe_job.sh
→ verificar terminal evidence
→ simular pseudos correctos
→ recolectar bundle
→ verificar bundle
```

No debe ejecutarse:

```text
SIESTA
SLURM real
MPI real
```

Guarda evidencia en:

```text
siestaflow/docs/validation/M3R_LOCAL_RUNTIME_DEMONSTRATION.md
```

---

# 24. Criterios de aceptación

M3R sólo puede aprobarse si:

```text
PROMPT_SELF_PERSISTED
DEFECT_A_FIXED
DEFECT_B_FIXED
ALL_DIRECT_PYTHON_COMPILES
ALL_BASH_SCRIPTS_PARSE
ALL_SLURM_SCRIPTS_PARSE
ALL_EMBEDDED_PYTHON_COMPILES
GENERATED_SLURM_EXECUTES_WITH_STUBS
INSPECT_JOB_EXECUTES_WITH_STUBS
SQUEUE_EMPTY_IS_NOT_SUCCESS
SACCT_TERMINAL_EVIDENCE_PASS
BUNDLE_COLLECTION_RUNTIME_PASS
PSEUDOPOTENTIAL_VERIFIER_PASS
PACKAGE_SECRET_SCAN_PASS
PACKAGE_PATH_SAFETY_PASS
ENGINEERING_DONOR_CROSSCHECK_COMPLETE
M3_REMOTE_PACKAGE_V2_REGENERATED
M0_M1_M2_M3_M3G_REGRESSION_PASS
CONTEXT_UNMODIFIED
NO_REMOTE_EXECUTION_PERFORMED
```

Si falla cualquier criterio:

```text
M3R_INCOMPLETE
REMOTE_PACKAGE_V2_NOT_APPROVED
```

---

# 25. Restricciones absolutas

No debes:

```text
editar la carpeta ya transferida a Yoltla
ejecutar el paquete en Yoltla
ejecutar SIESTA
ejecutar SLURM real
ejecutar MPI real
usar SSH automático
enviar sbatch
modificar geometrías
modificar FDF científicos
modificar pseudopotenciales
descargar archivos
alterar hashes científicos
copiar lógica QE incompatible
hacer commits
continuar a M3B
continuar a M4
```

---

# 26. Archivos de evidencia requeridos

Genera:

```text
siestaflow/docs/validation/M3R_RUNTIME_DEFECT_AUDIT.md
siestaflow/docs/validation/M3R_RUNTIME_DEFECT_AUDIT.json
siestaflow/docs/validation/M3R_ENGINEERING_DONOR_CROSSCHECK.md
siestaflow/docs/validation/M3R_ENGINEERING_DONOR_CROSSCHECK.json
siestaflow/docs/validation/M3R_TEST_EVIDENCE.md
siestaflow/docs/validation/M3R_LOCAL_RUNTIME_DEMONSTRATION.md
siestaflow/docs/validation/M3R_LIMITATIONS.md
```

Evita documentación redundante.

---

# 27. Informe final

Entrega:

```text
HITO: M3R_REMOTE_PROBE_RUNTIME_CORRECTION_AND_ENGINEERING_DONOR_CROSSCHECK
ESTADO:
PROMPT_PATH:
PROMPT_SHA256:
DEFECT_A:
DEFECT_B:
ADDITIONAL_DEFECTS:
SECURITY_DEFECTS:
PORTABILITY_DEFECTS:
FILES_CORRECTED:
ENGINEERING_DONOR:
DONOR_COMPONENTS_REVIEWED:
PORT_COUNT:
REFACTOR_COUNT:
REWRITE_COUNT:
DISCARD_COUNT:
EMBEDDED_PYTHON_VALIDATOR:
DIRECT_PYTHON_VALIDATION:
BASH_VALIDATION:
SLURM_VALIDATION:
GENERATED_SLURM_RUNTIME_TEST:
INSPECT_JOB_RUNTIME_TEST:
SACCT_CLASSIFICATION_TEST:
BUNDLE_COLLECTION_TEST:
PSEUDOPOTENTIAL_TEST:
SECRET_SCAN:
PATH_SAFETY:
PACKAGE_REVISION:
PACKAGE_MANIFEST:
PACKAGE_SHA256:
DOCUMENTATION:
PRUEBAS_M0:
PRUEBAS_M1:
PRUEBAS_M2:
PRUEBAS_M3:
PRUEBAS_M3G:
PRUEBAS_M3R:
PRUEBAS_FALLIDAS:
CONTEXTO:
REMOTE_EXECUTION:
LIMITACIONES:
NEXT_USER_ACTION:
```

Distingue:

```text
OBSERVED
EXECUTED_LOCALLY
DOCUMENTED_ONLY
SYNTHETIC
MISSING
CONTRADICTORY
```

---

# 28. Siguiente acción del usuario

Si M3R pasa, Codex debe instruir al usuario para:

1. renombrar o eliminar manualmente en Yoltla:

```text
M3_YOLTLA_ENVIRONMENT_PROBE
```

2. transferir la carpeta V2 completa;

3. verificar el paquete mediante:

```bash
python3 verify_local_package.py
```

4. no reutilizar archivos de V1;

5. ejecutar exactamente `EXACT_COMMANDS.md`.

No ejecutes estas acciones automáticamente.

---

# 29. STOP CONDITION

Detente cuando:

1. el prompt esté autopersistido;
2. los defectos A y B estén corregidos;
3. todos los heredocs Python compilen;
4. el script generado se ejecute con stubs;
5. `inspect_probe_job.sh` se ejecute con stubs;
6. la clasificación `sacct` esté probada;
7. el donante haya sido revisado y documentado;
8. el paquete V2 esté regenerado;
9. todas las regresiones pasen;
10. `context/` permanezca intacto;
11. no se haya realizado ejecución remota.

Finaliza exactamente con:

```text
PROMPT_SELF_PERSISTED
M3_RUNTIME_DEFECTS_CORRECTED
ENGINEERING_DONOR_CROSSCHECK_COMPLETE
EMBEDDED_PYTHON_VALIDATION_PASS
GENERATED_SLURM_RUNTIME_TEST_PASS
INSPECT_JOB_RUNTIME_TEST_PASS
SACCT_TERMINAL_EVIDENCE_PASS
M3_REMOTE_PACKAGE_V2_READY
ALL_REGRESSIONS_PASS
REAL_REMOTE_EVIDENCE_PENDING
M3R_COMPLETE_WAITING_FOR_HUMAN_REVIEW
```

No hagas commits.

No ejecutes el paquete.

No continúes a M3B.

No continúes a M4.

Espera revisión humana.
