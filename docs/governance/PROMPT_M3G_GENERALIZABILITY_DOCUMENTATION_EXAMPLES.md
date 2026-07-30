# PROMPT M3G — GENERALIZABILITY, DOCUMENTATION AND EXECUTABLE EXAMPLES

## 0. Autopersistencia

Antes de modificar cualquier otro archivo:

1. Guarda íntegramente este prompt en:

```text
siestaflow/docs/governance/PROMPT_M3G_GENERALIZABILITY_DOCUMENTATION_EXAMPLES.md
```

2. Calcula su SHA-256.

3. Registra ruta, fecha, tamaño y hash en:

```text
siestaflow/docs/context/CONTEXT_INVENTORY.md
```

4. Si la autopersistencia falla, detente con:

```text
PROMPT_SELF_PERSISTENCE_FAILED
M3G_NOT_STARTED
```

No hagas commits.

---

# 1. Hito autorizado

Ejecuta exclusivamente:

```text
M3G_GENERALIZABILITY_DOCUMENTATION_AND_EXECUTABLE_EXAMPLES
```

Estado de entrada:

```text
M0_ACCEPTED
M1_ACCEPTED
M2_ACCEPTED
M3_LOCAL_PASS
REMOTE_ENVIRONMENT_EVIDENCE_PENDING
```

Este hito puede ejecutarse localmente mientras se obtiene la evidencia remota de M3.

No ejecutes SIESTA, SLURM, MPI ni SSH.

No continúes a M4.

---

# 2. Objetivo

Asegurar que SIESTAFLOW sea un framework generalizable y no un script específico del proyecto de birnessita.

También debes crear:

1. documentación de usuario mantenida junto con el código;
2. sistema general de paquetes de proyecto;
3. sistema general de ejemplos ejecutables;
4. ejemplos técnicos con manifiestos de pseudopotenciales;
5. una instancia de referencia Mn/O;
6. pruebas que demuestren que nuevas especies y geometrías no requieren modificar el núcleo.

La arquitectura obligatoria es:

```text
núcleo genérico
→ adaptador de motor SIESTA
→ primitivas genéricas de campaña
→ paquetes externos de proyecto
→ paquetes externos de ejemplos
```

El proyecto DFT actual será:

```text
REFERENCE_PROJECT
INTEGRATION_VALIDATION_CASE
NOT_CORE_LOGIC
```

---

# 3. Prohibición de hardcoding científico

Dentro de:

```text
src/siestaflow/
```

no debe existir lógica fija dependiente de:

```text
Mn
O
Ca
Mg
MnO2
birnessita
grafeno
M1_
ADSORB_
Ca8w
Mg6w
geometrías concretas
hashes concretos de pseudopotenciales
valores 200/250/300/350 como serie obligatoria
fases exclusivas F0-F12
```

Estas cadenas pueden existir en:

```text
examples/
tests/fixtures/
reference_projects/
docs/
```

pero no como condiciones centrales del framework.

Está prohibido:

```python
if system_id == "M1_delta_MnO2_neutral_surface_control_v01":
    ...
```

También está prohibido:

```python
required_species = ["Mn", "O"]
```

dentro del núcleo o del adaptador general.

---

# 4. Separación arquitectónica

Mantén o implementa una separación equivalente a:

```text
src/siestaflow/
├── core/
├── project/
├── campaign/
├── hpc/
├── storage/
├── remote/
├── engines/
│   └── siesta/
├── plugins/
└── examples_api/

examples/
├── generic/
│   └── minimal_siesta_smoke/
└── reference_projects/
    └── birnessite_mn_o/

tests/
├── generalization/
├── examples/
└── fixtures/
```

No es obligatorio usar exactamente estas rutas, pero la separación conceptual sí es obligatoria.

No reescribas módulos que ya sean correctamente genéricos.

---

# 5. Contrato de paquetes de proyecto

Implementa un esquema versionado para paquetes externos:

```text
ProjectPackage/
├── project.yaml
├── systems/
├── structures/
├── pseudopotentials/
│   └── manifest.yaml
├── campaigns/
├── policies/
├── authorizations/
└── expected_contracts/
```

Un paquete de proyecto debe poder estar fuera del repositorio de SIESTAFLOW.

Añade una API y comandos equivalentes a:

```text
siestaflow project inspect <package>
siestaflow project validate <package>
siestaflow project load <package>
```

Cargar un nuevo sistema, especie, geometría o pseudopotencial no debe exigir modificar:

```text
src/siestaflow/
```

El paquete debe poder declarar:

```yaml
schema_version: 1

project:
  id: example_project
  engine: siesta

systems:
  - id: example_system
    structure: structures/example.xyz
    charge: 0
    species:
      - symbol: X
        pseudopotential: pseudo_x
      - symbol: Y
        pseudopotential: pseudo_y
```

Los símbolos X/Y son conceptuales para fixtures. El esquema real no debe restringirse a una lista cerrada de especies.

---

# 6. Campañas declarativas

Las campañas deben cargarse desde YAML o JSON.

Ejemplo:

```yaml
schema_version: 1

campaign:
  id: cutoff_sweep
  engine: siesta
  mode: adaptive_sequential

tasks:
  parameter:
    name: Mesh.Cutoff
    values:
      - 180 Ry
      - 240 Ry
      - 320 Ry

gates:
  after_task:
    - technical_completion
    - known_warnings
  after_series:
    - human_review
```

El worker no debe contener valores científicos fijos.

Las campañas M1, Mesh y k-grid actuales deben residir en el paquete de referencia, no en el núcleo.

El framework debe poder cargar una campaña con otros valores sin cambios de código.

---

# 7. Compuertas extensibles

El núcleo sólo debe contener compuertas generales:

```text
TechnicalCompletionGate
KnownWarningsGate
ArtifactPresenceGate
SCFConvergenceGate
HumanReviewGate
ParameterSeriesCompletionGate
```

Las compuertas particulares del proyecto, como:

```text
preservación OS
preservación de hidratación
convención de carga
aceptación del padre M1
```

deben registrarse mediante políticas o plugins del paquete de proyecto.

El `GateEngine` genérico no debe importar módulos del proyecto de referencia.

---

# 8. Manifiesto general de pseudopotenciales

El manifiesto debe aceptar un conjunto arbitrario de especies:

```yaml
schema_version: 1

pseudopotentials:
  X:
    id: pseudo_x
    filename: X.psml
    format: PSML
    sha256: null
    distribution_status: EXTERNAL

  Y:
    id: pseudo_y
    filename: Y.psml
    format: PSML
    sha256: null
    distribution_status: EXTERNAL
```

El auditor debe comparar:

```text
especies requeridas por el input
contra
especies declaradas en el manifiesto
contra
archivos localizados durante staging
```

No debe contener ramas especiales para Mn/O.

Los hashes Mn/O existentes deben estar únicamente en el paquete de referencia.

---

# 9. Sistema general de ejemplos

Implementa un contrato `ExamplePackage`:

```text
ExamplePackage/
├── example.yaml
├── README.md
├── structures/
├── inputs/
├── pseudopotentials/
│   └── manifest.yaml
├── campaigns/
└── expected_contracts/
```

Añade comandos equivalentes a:

```text
siestaflow examples list
siestaflow examples inspect <example-id>
siestaflow examples validate <example-id>
siestaflow examples stage <example-id> --pseudo-root <ruta>
siestaflow examples package <example-id>
siestaflow examples results import <bundle>
```

Los comandos deben operar con cualquier `ExamplePackage` válido.

No deben contener condiciones específicas para Mn/O.

---

# 10. Ejemplo genérico

Crea:

```text
examples/generic/minimal_siesta_smoke/
```

Debe ser una plantilla técnica general.

Debe permitir declarar externamente:

```text
estructura
especies
carga
spin técnico
pseudopotenciales
parámetros FDF
perfil de clúster
recursos
contrato técnico esperado
```

No tiene que incluir pseudopotenciales reales en Git.

Debe poder prepararse mediante un manifiesto y una ruta proporcionada por el usuario.

Su finalidad es demostrar:

```text
parseo
validación
staging
renderizado FDF
renderizado SLURM
empaquetado
importación
```

sin realizar interpretación científica.

---

# 11. Proyecto de referencia Mn/O

Crea:

```text
examples/reference_projects/birnessite_mn_o/
```

Debe incluir, como configuraciones y no como lógica Python central:

```text
smoke técnico Mn/O
M1_U0_FM sanity
campaña Mesh 200/250/300/350 Ry
manifiesto Mn/O con hashes auditados
políticas F0-F12 relevantes
```

Debe estar marcado en sus manifiestos y README como:

```text
REFERENCE_PROJECT
NOT_CORE_REQUIREMENT
NO_SCIENTIFIC_INTERPRETATION_FOR_SMOKE
```

El smoke Mn/O puede usar una estructura sintética mínima siempre que:

```text
se almacene sólo bajo examples/reference_projects/
se marque NON_SCIENTIFIC_TECHNICAL_FIXTURE
no sustituya la geometría científica M1
no se utilice para publicar energías
no modifique el protocolo científico
```

Prioriza una geometría técnica procedente de ejemplos oficiales de SIESTA si existe una fuente verificable. Si no existe, puede generarse una estructura sintética pequeña exclusivamente para validar lectura de Mn/O y SCF, con documentación explícita de que no representa un modelo físico del proyecto.

---

# 12. Staging de pseudopotenciales

El comando:

```text
siestaflow examples stage <example-id> --pseudo-root <ruta>
```

debe:

1. leer las especies del paquete;
2. localizar cada archivo requerido;
3. comprobar unicidad;
4. verificar formato;
5. verificar SHA-256 cuando esté definido;
6. comprobar legibilidad;
7. crear un workspace limpio;
8. copiar o enlazar según política explícita;
9. generar un manifiesto final con hashes;
10. bloquear faltantes, duplicados y discrepancias.

Estados:

```text
EXAMPLE_READY
EXAMPLE_BLOCKED_MISSING_PSEUDOS
EXAMPLE_BLOCKED_HASH_MISMATCH
EXAMPLE_BLOCKED_INVALID_MANIFEST
```

No descargues pseudopotenciales.

No sustituyas automáticamente un archivo incorrecto.

No incorpores archivos PSML al repositorio sin verificar licencia y política de redistribución.

---

# 13. Documentación como código

Crea o completa:

```text
README.md
CHANGELOG.md
CONTRIBUTING.md

docs/user/USER_MANUAL.md
docs/user/INSTALLATION.md
docs/user/QUICK_START.md
docs/user/CLI_REFERENCE.md
docs/user/TROUBLESHOOTING.md

docs/operations/YOLTLA_RUNBOOK.md
docs/operations/REMOTE_VALIDATION_WORKFLOW.md
docs/operations/RECOVERY_AND_RESUME.md

docs/scientific/SCIENTIFIC_GOVERNANCE.md
docs/scientific/CAMPAIGN_GATES.md

docs/developer/DEVELOPER_GUIDE.md
docs/developer/ARCHITECTURE.md
docs/developer/TESTING.md
```

La documentación debe describir únicamente funcionalidades implementadas.

Debe distinguir claramente:

```text
LOCAL
SIMULATED
PREVIEW
REMOTE_EVIDENCE_PENDING
REMOTE_VERIFIED
SCIENTIFICALLY_AUTHORIZED
```

No documentes como disponible una función futura.

Todos los comandos deben poder copiarse.

Incluye códigos de salida y resultados esperados.

---

# 14. Política de actualización documental

Incorpora como norma del proyecto:

```text
Todo comando nuevo actualiza CLI_REFERENCE.md.
Todo flujo nuevo actualiza USER_MANUAL.md.
Todo cambio remoto actualiza YOLTLA_RUNBOOK.md.
Todo estado o gate nuevo actualiza SCIENTIFIC_GOVERNANCE.md.
Toda modificación visible se registra en CHANGELOG.md.
```

Un hito no debe declararse completo si modifica la interfaz pública sin actualizar la documentación.

---

# 15. Pruebas de generalización

Crea al menos dos proyectos sintéticos:

```text
PROJECT_ALPHA
  especies X/Y
  una estructura
  un sweep con valores propios

PROJECT_BETA
  especies A/B/C
  otra estructura
  una secuencia diferente
```

Ambos deben completar:

```text
load
→ validate
→ stage mediante pseudos sintéticos
→ render input
→ create campaign
→ simulate
→ parse
→ gate
→ report
```

sin modificar el código entre ejecuciones.

No uses Mn/O en estas dos pruebas.

---

# 16. Auditoría anti-hardcoding

Añade una prueba estática sobre:

```text
src/siestaflow/
```

que busque, al menos:

```text
M1_
MnO2
birnessite
ADSORB_
Ca8w
Mg6w
hashes Mn/O
rutas del snapshot
200,250,300,350 como serie rígida
```

La prueba debe fallar cuando esas referencias afecten lógica central.

Se permiten únicamente en:

```text
examples/
tests/fixtures/reference_projects/
docs/
```

No basta con buscar texto: revisa también valores por defecto, ramas condicionales y registros construidos en código.

---

# 17. Pruebas de documentación y ejemplos

Añade pruebas que verifiquen:

```text
todos los comandos documentados existen
los ejemplos YAML/JSON validan contra esquema
los enlaces internos principales existen
las rutas documentadas son válidas
los paquetes de ejemplo se pueden inspeccionar
pseudo faltante se bloquea
hash incorrecto se bloquea
dry-run no produce efectos
paquete remoto preview es reproducible
bundle sintético nunca se promueve a evidencia real
```

Comprueba que `--help` y `CLI_REFERENCE.md` no entren en contradicción.

---

# 18. Regresiones

Ejecuta todas las pruebas M0, M1, M2 y M3.

Resultado requerido:

```text
0 REGRESSIONS
```

Verifica también:

```text
context/ = 642/642 archivos intactos
```

No modifiques el paquete M3 ya generado salvo para actualizar documentación o compatibilidad general demostrablemente necesaria.

---

# 19. Documentación de resultados

Genera:

```text
docs/validation/M3G_GENERALIZABILITY_AUDIT.md
docs/validation/M3G_EXAMPLES_TEST_EVIDENCE.md
docs/validation/M3G_DOCUMENTATION_CONSISTENCY.md
docs/validation/M3G_LIMITATIONS.md
```

La auditoría debe clasificar los acoplamientos encontrados como:

```text
CONFIGURATION_ONLY
REFERENCE_EXAMPLE_ONLY
REFACTOR_REQUIRED
BLOCKING_HARDCODING
```

Corrige todos los casos `REFACTOR_REQUIRED` y `BLOCKING_HARDCODING`.

---

# 20. Criterios de aceptación

El hito sólo puede aprobarse si:

```text
PROMPT_SELF_PERSISTED
CORE_PROJECT_AGNOSTIC
ENGINE_ADAPTER_PROJECT_AGNOSTIC
ARBITRARY_SPECIES_MANIFEST_PASS
EXTERNAL_PROJECT_PACKAGE_PASS
DECLARATIVE_CAMPAIGN_PASS
EXTENSIBLE_GATES_PASS
GENERIC_EXAMPLE_PACKAGE_PASS
REFERENCE_PROJECT_ISOLATED
TWO_DISTINCT_SYNTHETIC_PROJECTS_PASS
PSEUDOPOTENTIAL_STAGING_PASS
DOCUMENTATION_AS_CODE_PASS
CLI_DOCUMENTATION_CONSISTENCY_PASS
NO_PROJECT_SPECIFIC_HARDCODING
M0_M1_M2_M3_REGRESSION_PASS
CONTEXT_UNMODIFIED
NO_REAL_SIESTA_EXECUTION
```

Si falla cualquier criterio:

```text
M3G_INCOMPLETE
```

---

# 21. Restricciones

No ejecutes:

```text
SIESTA real
SLURM real
MPI real
SSH
sbatch
M1 sanity
Mesh real
```

No descargues pseudopotenciales.

No modifiques geometrías científicas.

No promociones fixtures sintéticos.

No hagas commits.

No continúes a M3B ni M4.

---

# 22. Informe final

Entrega:

```text
HITO: M3G_GENERALIZABILITY_DOCUMENTATION_AND_EXECUTABLE_EXAMPLES
ESTADO:
PROMPT_PATH:
PROMPT_SHA256:
HARDCOUPLINGS_FOUND:
HARDCOUPLINGS_FIXED:
CORE_GENERALIZATION:
PROJECT_PACKAGE_SCHEMA:
EXAMPLE_PACKAGE_SCHEMA:
GENERIC_EXAMPLE:
REFERENCE_PROJECT:
PSEUDOPOTENTIAL_STAGING:
DOCUMENTATION:
CLI_DOCUMENTATION:
PROJECT_ALPHA:
PROJECT_BETA:
PRUEBAS_M0:
PRUEBAS_M1:
PRUEBAS_M2:
PRUEBAS_M3:
PRUEBAS_M3G:
PRUEBAS_FALLIDAS:
CONTEXTO:
LIMITACIONES:
VALIDACIÓN_REAL:
SIGUIENTE_ACCIÓN:
```

---

# 23. STOP CONDITION

Detente cuando:

1. el prompt esté autopersistido;
2. el núcleo sea agnóstico al proyecto;
3. el paquete de proyecto externo funcione;
4. los ejemplos genérico y de referencia existan;
5. el staging de pseudos esté probado;
6. los dos proyectos sintéticos pasen;
7. los manuales existan y concuerden con la CLI;
8. todas las regresiones pasen;
9. no se haya ejecutado SIESTA real.

Finaliza exactamente con:

```text
PROMPT_SELF_PERSISTED
GENERALIZABILITY_AUDIT_COMPLETE
CORE_REMAINS_PROJECT_AGNOSTIC
ARBITRARY_PROJECT_PACKAGE_SUPPORTED
EXECUTABLE_EXAMPLES_LOCAL_PASS
DOCUMENTATION_AS_CODE_PASS
NO_PROJECT_SPECIFIC_HARDCODING
REAL_SIESTA_SMOKE_PENDING
M3G_COMPLETE_WAITING_FOR_HUMAN_REVIEW
```
