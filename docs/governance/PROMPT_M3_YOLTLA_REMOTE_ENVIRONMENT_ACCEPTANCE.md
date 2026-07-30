# PROMPT M3 — YOLTLA REMOTE ENVIRONMENT ACCEPTANCE

## 0. Autopersistencia

Antes de modificar cualquier otro archivo:

1. Guarda íntegramente este prompt en:

```text
siestaflow/docs/governance/PROMPT_M3_YOLTLA_REMOTE_ENVIRONMENT_ACCEPTANCE.md
```

2. Calcula su SHA-256.

3. Registra ruta, fecha y hash en:

```text
siestaflow/docs/context/CONTEXT_INVENTORY.md
```

4. Si la autopersistencia falla, detente con:

```text
PROMPT_SELF_PERSISTENCE_FAILED
M3_NOT_STARTED
```

El usuario no debe crear ni editar archivos manualmente.

---

# 1. Hito autorizado

Ejecuta exclusivamente:

```text
M3_YOLTLA_REMOTE_ENVIRONMENT_ACCEPTANCE
```

Estado de entrada aprobado:

```text
M0_ACCEPTED
M1_ACCEPTED
M2_ACCEPTED
FUNCTIONAL_SIESTA_VERTICAL_SLICE_PASS
SANITY_END_TO_END_LOCAL_PASS
PERSISTENT_MESH_SIMULATION_PASS
REAL_SIESTA_VALIDATION_PENDING
```

No repitas M0, M1 o M2.

No continúes a la sanity real.

No hagas commits.

---

# 2. Objetivo

Convertir el perfil Yoltla de:

```text
UNVERIFIED_FOR_SIESTA
```

a uno de estos estados, exclusivamente mediante evidencia real recuperada del clúster:

```text
REMOTE_ENVIRONMENT_ACCEPTED
REMOTE_ENVIRONMENT_REVIEW
REMOTE_ENVIRONMENT_FAILED
REMOTE_EVIDENCE_PENDING
```

Debes preparar un paquete remoto que permita verificar:

```text
SLURM
cuenta
partición
QoS
nodos
límites de tiempo
módulos
ejecutable SIESTA
versión SIESTA
launcher MPI
variables del entorno
filesystem y scratch
sacct
señales
pseudopotenciales Mn/O
hashes
```

Este hito no ejecutará ningún cálculo científico.

---

# 3. Modelo operativo

Codex trabaja localmente.

El usuario realizará manualmente:

```text
transferir paquete a Yoltla
→ ejecutar probe de login
→ enviar probe SLURM no científico
→ recolectar resultados
→ descargar bundle
→ entregarlo nuevamente a Codex
```

Está prohibido implementar:

```text
SSH automático
SCP automático
credenciales
claves
tokens
envío remoto desde Windows
```

Codex debe generar comandos exactos de copiar y pegar. El usuario no debe editar scripts o YAML manualmente.

---

# 4. Alcance estricto

Implementa únicamente lo necesario para:

1. generar el paquete de caracterización;
2. ejecutar probes no científicos;
3. recolectar evidencia;
4. verificar hashes;
5. importar el bundle;
6. sintetizar un perfil Yoltla;
7. decidir si puede prepararse M4.

No añadas:

```text
nuevos parsers FDF
nuevas campañas científicas
U/spin
relajaciones
DOS/PDOS
counterpoise
optimización de rendimiento
scheduler inteligente
nuevas abstracciones no necesarias
```

M0, M1 y M2 deben permanecer estables.

---

# 5. Paquete remoto requerido

Genera:

```text
siestaflow/remote_validation/M3_YOLTLA_ENVIRONMENT_PROBE/
├── README_RUN.md
├── EXACT_COMMANDS.md
├── PROBE_CHECKLIST.md
├── probe_manifest.json
├── probe_manifest.sha256
├── expected_evidence.json
├── run_login_probe.sh
├── prepare_scheduler_probe.py
├── submit_environment_probe.slurm
├── inspect_probe_job.sh
├── collect_probe_results.sh
├── verify_local_package.py
├── scripts/
└── checksums.sha256
```

El paquete debe ser reproducible.

No debe contener:

```text
secretos
credenciales
pseudopotenciales
FDF productivos
geometrías
comandos de sanity
comandos de producción
```

---

# 6. Probe de login

`run_login_probe.sh` debe recolectar, sin modificar el entorno permanente:

```text
fecha UTC
hostname
usuario
sistema operativo
arquitectura
shell
ulimit
quota o espacio disponible cuando sea accesible
module command disponible
module list
búsqueda controlada de módulos SIESTA
command -v para comandos relevantes
sinfo resumido
squeue del usuario
sacct disponible
scontrol disponible
particiones visibles
variables SLURM presentes
MPI disponible
srun --version
mpirun --version
mpiexec --version
mpiexec.hydra --version
```

Debe evitar volcados enormes.

Debe evitar registrar:

```text
variables con TOKEN
PASSWORD
SECRET
KEY
CREDENTIAL
COOKIE
```

Debe generar archivos estructurados y un log humano.

No debe cargar automáticamente todos los módulos disponibles.

---

# 7. Detección de SIESTA

El probe debe buscar SIESTA de manera controlada:

```text
module spider siesta
module avail siesta
module show <candidato>
command -v siesta
command -v siesta-5.4.2
```

Utiliza únicamente comandos disponibles.

No debe asumir el nombre del módulo o ejecutable.

Una prueba del ejecutable está permitida sólo cuando exista una forma no científica y documentada de obtener versión o ayuda.

Ejemplos conceptuales:

```text
siesta --version
siesta --help
```

No hardcodees estas opciones sin verificarlas.

Si no existe una invocación segura demostrada, registra:

```text
SIESTA_EXECUTABLE_DISCOVERED_VERSION_COMMAND_UNVERIFIED
```

No ejecutes un FDF.

No alimentes geometrías o inputs al ejecutable.

---

# 8. Probe dentro de SLURM

`submit_environment_probe.slurm` será un trabajo no científico.

Debe comprobar dentro de un nodo de cómputo:

```text
SLURM_JOB_ID
SLURM_JOB_PARTITION
SLURM_JOB_ACCOUNT
SLURM_JOB_QOS
SLURM_NNODES
SLURM_NTASKS
SLURM_CPUS_PER_TASK
SLURM_JOB_END_TIME
hostname
module list
rutas de ejecutables
versiones MPI
versión SIESTA cuando sea seguro
filesystem visible
scratch
señales
```

No debe:

```text
ejecutar un cálculo SIESTA
usar FDF
usar pseudopotenciales
usar más de recursos mínimos
ejecutar benchmarks
```

Debe incluir:

```text
#SBATCH --signal=B:USR1@60
```

o la forma equivalente permitida, y registrar si la señal puede recibirse de manera controlada.

No debe enviarse automáticamente.

---

# 9. Perfil candidato

La evidencia MD/LAMMPS observada:

```yaml
partition: q1d-20p
account: vini
nodes: 1
ntasks: 20
launcher: mpiexec.hydra
```

puede usarse exclusivamente como:

```text
NON_SIESTA_CANDIDATE_PROFILE
```

No debe adoptarse como perfil SIESTA.

`prepare_scheduler_probe.py` debe:

1. leer la evidencia del probe de login;
2. identificar cuentas y particiones candidatas;
3. generar el script SLURM sin edición manual;
4. bloquearse si no existe una combinación defendible;
5. conservar claramente el origen de cada valor.

No inventes valores.

---

# 10. Pseudopotenciales Mn/O

El paquete debe incluir únicamente un manifiesto con los hashes esperados de Mn y O ya auditados.

Debe permitir al usuario ejecutar un comando como:

```text
./collect_probe_results.sh --pseudo-root <ruta>
```

El script debe buscar los archivos candidatos y verificar:

```text
existencia
nombre
formato
tamaño
SHA-256
legibilidad
```

No debe:

```text
descargar
copiar
renombrar
modificar
redistribuir
```

Estados:

```text
PSEUDOS_MN_O_HASH_VERIFIED
PSEUDOS_MN_O_MISSING
PSEUDOS_MN_O_HASH_MISMATCH
PSEUDOS_MN_O_REVIEW
```

---

# 11. Evidencia de SLURM

Después del probe, recolecta cuando estén disponibles:

```text
job ID
sbatch output
squeue durante ejecución
sacct después de ejecución
State
ExitCode
Elapsed
AllocTRES
MaxRSS
NodeList
partition
account
QoS
stdout
stderr
```

Regla vinculante:

```text
un trabajo ausente de squeue no equivale a éxito
```

La aceptación requiere evidencia terminal explícita mediante `sacct`, exit code o evidencia equivalente.

---

# 12. Seguridad

Todos los scripts deben usar:

```bash
set -euo pipefail
```

cuando sea apropiado.

Deben:

```text
rechazar path traversal
rechazar sobrescritura silenciosa
usar directorios únicos
calcular hashes
preservar stdout/stderr
redactar secretos
registrar códigos de salida
```

No deben:

```text
usar sudo
cambiar módulos permanentemente
modificar dotfiles
modificar shell startup
instalar software
crear entornos Conda
descargar paquetes
```

---

# 13. Bundle de resultados

`collect_probe_results.sh` debe producir:

```text
M3_YOLTLA_ENVIRONMENT_RESULTS_<timestamp>.tar.gz
```

Contenido:

```text
results_manifest.json
results_manifest.sha256
login_probe/
scheduler_probe/
siesta_discovery/
mpi_discovery/
slurm_accounting/
filesystem/
pseudo_verification/
stdout/
stderr/
checksums.sha256
```

El bundle debe registrar:

```text
evidence_type: REAL_REMOTE_ENVIRONMENT_PROBE
scientific_calculation_performed: false
```

---

# 14. Importación local

Añade o completa:

```text
siestaflow remote environment import <bundle>
```

Debe:

1. verificar hashes;
2. verificar identidad del probe;
3. rechazar bundle sintético como evidencia real;
4. detectar archivos faltantes;
5. detectar alteraciones;
6. analizar SLURM;
7. analizar módulos;
8. analizar SIESTA;
9. analizar MPI;
10. analizar pseudopotenciales;
11. generar un perfil candidato;
12. producir una decisión.

Estados:

```text
REMOTE_ENVIRONMENT_ACCEPTED
REMOTE_ENVIRONMENT_REVIEW
REMOTE_ENVIRONMENT_FAILED
REMOTE_EVIDENCE_INCOMPLETE
```

No debe promover un perfil únicamente porque el trabajo SLURM terminó.

---

# 15. Perfil Yoltla generado

Cuando exista evidencia real suficiente, genera:

```text
siestaflow/config/cluster_profiles/yoltla_siesta.yaml
```

Debe incluir por campo:

```yaml
value: null
evidence_status: MISSING
source_file: null
observed_at: null
```

Campos mínimos:

```text
scheduler
partition
account
QoS
nodes
ntasks
cpus_per_task
memory
walltime
signal
launcher
launcher_command
module_commands
siesta_executable
siesta_version
scratch_root
project_root
pseudopotential_root
sacct_available
```

Estados de evidencia:

```text
OBSERVED
VERIFIED
INFERRED
MISSING
CONTRADICTORY
```

Sólo valores `OBSERVED` o `VERIFIED` pueden utilizarse después para renderizar un paquete ejecutable.

---

# 16. Decisión de aceptación

`REMOTE_ENVIRONMENT_ACCEPTED` requiere:

```text
SLURM job terminal demostrado
cuenta verificada
partición verificada
comandos SLURM funcionales
SIESTA localizado
versión SIESTA obtenida o evidencia equivalente suficiente
launcher identificado con evidencia
filesystem de trabajo verificado
Mn/O localizados y hash verificado
manifiesto completo
sin contradicciones bloqueantes
```

Cuando falte algún requisito:

```text
REMOTE_ENVIRONMENT_REVIEW
```

No reduzcas el criterio para aprobar.

---

# 17. Pruebas locales

Antes de entregar el paquete:

1. ejecuta todas las pruebas M0, M1 y M2;
2. prueba generación reproducible del paquete;
3. prueba que no contenga secretos;
4. prueba path traversal;
5. prueba bundles sintéticos válidos, alterados e incompletos;
6. prueba redacción de variables sensibles;
7. prueba que un `squeue` vacío no produzca aceptación;
8. prueba que un pseudo con hash incorrecto bloquee;
9. prueba que campos faltantes permanezcan `null`;
10. prueba que no se ejecute `sbatch` localmente.

`context/` debe permanecer 642/642 intacto.

---

# 18. Demostración local

Ejecuta en un directorio temporal:

```text
generar paquete M3
→ verificar hashes
→ simular probe remoto
→ crear bundle sintético
→ importar bundle
→ producir REMOTE_ENVIRONMENT_REVIEW o ACCEPTED según fixture
→ generar perfil con trazabilidad por campo
```

Los fixtures sintéticos deben permanecer explícitamente marcados y nunca promoverse como evidencia real.

Documenta en:

```text
siestaflow/docs/validation/M3_LOCAL_DEMONSTRATION.md
```

---

# 19. Documentación

Crea únicamente:

```text
siestaflow/docs/operations/M3_YOLTLA_PROBE_WORKFLOW.md
siestaflow/docs/validation/M3_TEST_EVIDENCE.md
siestaflow/docs/validation/M3_LOCAL_DEMONSTRATION.md
siestaflow/docs/validation/M3_LIMITATIONS.md
```

Actualiza:

```text
README.md
CONTEXT_INVENTORY.md
```

No generes documentación redundante.

---

# 20. Restricciones absolutas

No debes:

```text
ejecutar SIESTA científicamente
usar un FDF
ejecutar la sanity
ejecutar Mesh
enviar sbatch desde el entorno local
usar SSH automático
instalar software en Yoltla
descargar pseudopotenciales
adoptar el perfil LAMMPS como perfil SIESTA
inventar configuración
hacer commits
continuar a M4
```

---

# 21. Entregable inmediato de esta ejecución local

Esta ejecución de Codex debe terminar con:

```text
paquete M3 generado
importador implementado
pruebas locales completas
comandos remotos exactos documentados
REMOTE_EVIDENCE_PENDING
```

No puede declarar `REMOTE_ENVIRONMENT_ACCEPTED` antes de que el usuario ejecute el probe en Yoltla y devuelva el bundle real.

---

# 22. Informe final

Entrega:

```text
HITO: M3_YOLTLA_REMOTE_ENVIRONMENT_ACCEPTANCE
ESTADO:
PROMPT_PATH:
PROMPT_SHA256:
ARCHIVOS_CREADOS:
ARCHIVOS_MODIFICADOS:
CAMBIOS_EN_M0_M1_M2:
PAQUETE_REMOTO:
LOGIN_PROBE:
SLURM_PROBE:
SIESTA_DISCOVERY:
MPI_DISCOVERY:
PSEUDOPOTENTIAL_VERIFICATION:
IMPORTADOR:
PERFIL_YOLTLA:
PRUEBAS_M0:
PRUEBAS_M1:
PRUEBAS_M2:
PRUEBAS_M3:
PRUEBAS_FALLIDAS:
CONTEXTO:
DEMOSTRACIÓN_LOCAL:
EVIDENCIA_REMOTA:
LIMITACIONES:
SIGUIENTE_ACCIÓN_DEL_USUARIO:
SIGUIENTE_HITO:
```

---

# 23. STOP CONDITION

En esta primera ejecución de M3, detente cuando:

1. el prompt esté autopersistido;
2. el paquete M3 esté generado;
3. el importador funcione con fixtures;
4. las regresiones M0–M2 pasen;
5. `context/` esté intacto;
6. existan comandos exactos para el usuario;
7. no se haya ejecutado nada remotamente.

El cierre debe terminar exactamente con:

```text
PROMPT_SELF_PERSISTED
YOLTLA_ENVIRONMENT_PROBE_PACKAGE_READY
REMOTE_ENVIRONMENT_IMPORTER_LOCAL_PASS
M0_M1_M2_REGRESSION_PASS
REAL_REMOTE_EVIDENCE_PENDING
NO_SCIENTIFIC_SIESTA_RUN_PERFORMED
M3_REMOTE_EXECUTION_WAITING_FOR_USER
```

No continúes a M4.
No hagas commits.
Espera el bundle real de Yoltla.
