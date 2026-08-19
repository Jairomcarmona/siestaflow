# Gobernanza de desarrollo de QRAFT

Estado: obligatoria para cambios nuevos
Ámbito: una sola base de código, authoring local y runtime remoto derivado

Esta política complementa el
[`QRAFT_BACKBONE.md`](../design/QRAFT_BACKBONE.md). La autoridad final
combina contratos, pruebas deterministas, evidencia HPC, inspección del diff y
aceptación del investigador; ninguna herramienta sustituye esa autoridad.

## 1. Flujo de cambio

```text
especificación humana
→ implementación acotada
→ pruebas deterministas proporcionales al riesgo
→ auditoría independiente
→ revisión humana
→ commit o rechazo
```

Un mantenedor individual puede implementar y verificar cambios de bajo riesgo,
pero no puede autoaceptar evidencia científica ni cerrar en solitario un cambio
crítico. La revisión independiente puede ser otra persona o una nueva sesión de
auditoría con el requisito original, el diff completo, los contratos, las
salidas de prueba y la evidencia HPC.

## 2. Git y ramas

- `main` permanece localmente verificable.
- Los cambios no triviales usan ramas cortas como `feat/<alcance>`,
  `fix/<alcance>`, `docs/<alcance>`, `phase3/<alcance>` o
  `release/<version>`.
- No existe una rama permanente de “usuario”; las distribuciones se derivan de
  commits identificables de la misma base de código.
- No se exige GitFlow ni una jerarquía empresarial a un equipo pequeño.
- Una release identifica un commit; un tag nunca sustituye el expediente de
  aceptación.

No se inventa `user.name` ni `user.email`. Si falta identidad, se prepara y
verifica el árbol, pero el propietario realiza el commit después de configurar
Git.

## 3. Commits

Cada unidad lógica y verificable produce un commit atómico. No se mezclan
features, refactors y documentación sin relación, ni se crean microcommits sin
significado. Se prefieren mensajes Conventional Commits:

```text
feat(runtime): ...
fix(hydra): ...
test(phase3): ...
docs(governance): ...
docs(phase3): ...
refactor(compiler): ...
chore(release): ...
```

Antes del commit se inspeccionan `git status --short`, `git diff --check`, el
diff completo y `git diff --stat`. El commit se rechaza si fallan los gates,
si contiene cambios ajenos o si el mensaje no describe la unidad lógica. Los
artefactos generados sólo se versionan cuando son evidencia o fixtures
deliberados y revisados.

Una transición de fase siempre usa un commit dedicado distinto del commit que
introdujo la función aceptada.

## 4. Árboles sucios

La política para paquetes formales es **rechazar un árbol sucio**. Una release
candidate o paquete de aceptación sólo es publicable cuando
`SOURCE_TREE_DIRTY=false` y el commit fuente existe. Un paquete exploratorio
puede generarse desde un árbol sucio únicamente si se marca de forma inequívoca
como no publicable.

La implementación 0.2 de `run prepare` todavía no captura el commit ni el
estado dirty. Hasta implementar esos campos, su paquete puede probar ingeniería
local, pero necesita un registro de build externo verificable antes de ser
considerado paquete formal de aceptación. La incorporación de estos campos se
gobierna por el contrato de run/paquete en Fase 3 y no se simula en documentos.

## 5. Riesgo y gates

### Riesgo bajo

Documentación, mensajes, formato, ZIP, checksums y ejemplos sin cambio
semántico. Requiere revisión del diff, `git diff --check` y pruebas focalizadas;
se ejecuta la regresión completa cuando el documento rector, empaquetado o
comandos de verificación cambian.

### Riesgo medio

CLI, parsers, validaciones, empaquetado, constructores o cambios coordinados
entre módulos sin alterar contratos. Requiere pruebas unitarias, integración
local relevante, regresión completa y revisión independiente del diff.

### Riesgo alto

`workflow.lock`, `run.lock`, contratos, hashes, artefactos, persistencia,
señales, recuperación, reanudación, MPI/Hydra, recursos, declaración de éxito,
DM, geometría o interpretación científica. Requiere pruebas unitarias e
integrales, auditoría independiente y, cuando el comportamiento depende del
cluster, aceptación HPC real. Una prueba WSL no sustituye Yoltla.

La auditoría emite uno de:

```text
APPROVED_FOR_MERGE
CONDITIONALLY_APPROVED
REJECTED
```

Evalúa alcance, invariantes, compatibilidad, pruebas, cambio científico, riesgos
silenciosos, deuda, documentación y evidencia pendiente.

## 6. Codex y automatización

Codex puede implementar, generar pruebas, auditar, analizar evidencia y ayudar
con documentación. No puede ser simultáneamente la única autoridad de
implementación y aceptación de un cambio crítico. Para alto riesgo, la
auditoría preferida usa una sesión nueva que reciba material primario y no sólo
el resumen del implementador.

Codex sólo crea commits cuando el alcance está autorizado, el diff fue
inspeccionado, los gates pasan, la identidad Git es real, no hay cambios ajenos
y el informe devuelve el SHA. No hace push, no crea tags ni ejecuta jobs
remotos sin autorización explícita.

## 7. Pruebas y CI

El gate local base es:

```bash
git diff --check
python -m compileall -q src
python -m pytest -q
```

Los cambios de distribución añaden una construcción limpia de wheel/sdist; los
de documentación comprueban enlaces relativos, encabezados, fases, versiones y
rutas locales. Si falta contexto externo, el resultado se separa en `PASS`,
`FAIL`, `SKIPPED` y `BLOCKED_BY_EXTERNAL_CONTEXT` sin convertir bloqueos en
éxitos.

El repositorio no tiene CI versionada en el corte 0.2 auditado. Hasta crear CI
Linux en Fase 8, los gates locales y su salida deben adjuntarse a la revisión.
CI futura no debe contener secretos ni afirmar aceptación HPC sin importar
evidencia firmada del job correspondiente.

## 8. ADR

Se requiere ADR antes de introducir o cambiar:

- la ruta canónica;
- contratos o formatos de locks;
- persistencia, journal append-only o reanudación;
- modelo de artefactos o descubrimiento de plugins;
- perfiles incompatibles;
- Parsl u otro backend;
- una base de datos o servicio externo.

El ADR registra alternativas, consecuencias, compatibilidad, migración,
evidencia y estado. La convención y plantilla están en
[`docs/adr/`](../adr/README.md). No se escriben ADR retrospectivos vacíos.

## 9. Transición de fase y aceptación remota

Una transición formal necesita:

1. expediente basado en
   [`PHASE_ACCEPTANCE_TEMPLATE.md`](../validation/PHASE_ACCEPTANCE_TEMPLATE.md);
2. auditoría independiente;
3. release status y roadmap actualizados;
4. commit dedicado;
5. changelog actualizado;
6. tag anotado sólo cuando corresponda a una versión autorizada;
7. referencias separadas a evidencia local y remota;
8. aceptación humana identificada.

La Fase 3 no puede cerrarse hasta ejecutar en Yoltla un paquete limpio generado
por `run prepare` que complete padre → DM → hijo, demuestre lectura de la DM y
reconcilie evidencia. SIESTA/Slurm real en WSL es integración local realista,
pero no prueba módulos institucionales, Hydra multinodo, scheduler, señales ni
sistema de archivos de Yoltla.

## 10. Releases y distribución

Editable, wheel/sdist y paquete HPC son distribuciones de un mismo commit. Una
release requiere changelog, metadata y compatibilidad, no sólo pruebas verdes.
Las versiones alpha, beta y release candidate usan PEP 440. No se incrementa
la versión al cerrar documentación ni por una aceptación exclusivamente local.

No se exige completar Fase 8 para cerrar la aceptación técnica de Fase 3, pero
una distribución para usuarios externos sí debe superar los gates de Fase 8.

## 11. Trazabilidad

Un paquete formal de aceptación o release debe registrar:

```text
QRAFT_VERSION
SOURCE_COMMIT
SOURCE_TREE_DIRTY
WORKFLOW_LOCK_SHA256
RUN_LOCK_SHA256
EXECUTION_PROFILE_SHA256
PACKAGE_SHA256
BUILD_TIMESTAMP
```

La cadena verificable es:

```text
commit → distribución → paquete → job Slurm → attempt
       → artifact → evidence → result
```

En 0.2 ya existen la versión en paquete Python, hashes del workflow lock y
perfil en `run.lock.json`, hash del propio envelope de run durante preparación,
hashes de archivos del paquete y SHA-256 del ZIP devuelto por el builder. Faltan
captura persistida y uniforme de commit, árbol sucio y timestamp de build, así
como un campo contractual persistido para el hash del paquete final. Estos
gaps pertenecen al contrato run/paquete de Fase 3; una eventual migración del
schema exige ADR.

## 12. Autoridad humana

El investigador acepta decisiones científicas, perfiles promovidos y evidencia
remota. El mantenedor acepta ingeniería después de pruebas y revisión. Los
contratos y hashes demuestran identidad; no demuestran por sí mismos validez
física. Ante conflicto, se conserva la evidencia, se documenta la discrepancia
y se detiene la promoción.
