# QRAFT — columna vertebral del proyecto

Estado: documento rector estable
Software de referencia: QRAFT 0.2 alpha

El estado operativo vigente se mantiene en
[`QRAFT_0_2_RELEASE_STATUS.md`](QRAFT_0_2_RELEASE_STATUS.md) y la
secuencia de entrega en
[`QRAFT_PRODUCT_ROADMAP.md`](QRAFT_PRODUCT_ROADMAP.md). Este
documento define la misión, los límites y los invariantes que no deben
depender de un corte temporal.

## 1. Misión y autoridad científica

QRAFT transforma una intención científica declarada en un workflow DFT
autocontenido, verificable y reproducible para entornos HPC. Representa
dependencias científicas mediante un DAG tipado, transfiere artefactos con
procedencia, ejecuta decisiones numéricas previamente autorizadas y conserva
evidencia suficiente para explicar cada resultado.

El investigador conserva la autoridad sobre funcionales, Hubbard U, carga,
spin, modelos, criterios de convergencia y validez científica. Una terminación
técnica correcta no equivale a aceptación científica.

## 2. Límites

QRAFT no debe:

- elegir silenciosamente parámetros o modelos científicos;
- presentar heurísticas como leyes físicas;
- modificar la física durante una recuperación técnica;
- inferir validez científica de un código de salida;
- depender de Codex, internet, una base de datos externa o un daemon en login;
- instalar MPI, SIESTA o bibliotecas del sistema en el cluster;
- ocultar comandos, entradas, transformaciones o evidencia;
- mantener dos implementaciones de producción con semánticas distintas.

## 3. Vocabulario estable

- **Project**: investigación, fuentes y políticas bajo autoridad humana.
- **WorkflowDefinition**: DAG científico declarativo todavía no bloqueado.
- **Workflow**: DAG resuelto y tipado.
- **Campaign**: conjunto relacionado de cálculos o barridos.
- **Task**: nodo tipado del DAG.
- **Run**: ejecución concreta derivada de un workflow bloqueado.
- **Attempt**: intento individual de una tarea.
- **Artifact**: entrada o resultado con identidad, tipo, hash y procedencia.
- **Dependency**: relación de control o transferencia de datos.
- **Checkpoint**: estado reutilizable para continuar una tarea.
- **Evidence**: registro verificable de ejecución o decisión.
- **Execution profile**: configuración de recursos y launcher revisada para un
  entorno concreto.
- **Executor**: adaptador que ejecuta tareas en un entorno determinado.

## 4. Una base de código, varias distribuciones

Existe una sola base de código. De ella se derivan:

1. una instalación editable para desarrollo;
2. una wheel o sdist instalable para authoring local;
3. un paquete remoto autocontenido y mínimo para HPC;
4. plugins externos futuros cuando exista un contrato público adecuado.

Estas son formas de distribución, no ediciones, forks ni implementaciones
independientes. La distribución Python se gobierna mediante `pyproject.toml`,
`build`, wheel/sdist y `pip` o `pipx` cuando corresponda. CMake sólo sería
admisible si se incorporara un componente nativo propio que necesitara
compilación y un ADR justificara la decisión.

## 5. Superficies local y remota

### Authoring local

La superficie local importa y valida entradas, compila el DAG, genera locks,
prepara paquetes e inspecciona evidencia y resultados. Puede ofrecer
dependencias opcionales de usuario que no formen parte del runtime remoto.

### Runtime remoto

El runtime planifica dentro de una asignación, lanza MPI, transfiere
artefactos, evalúa gates autorizados, persiste intentos, recupera estado y
produce evidencia. Debe ser pequeño, autocontenido y operar sin internet,
Codex, servicios externos, instalación global persistente ni procesos
permanentes en el nodo de login.

## 6. Trayectoria canónica

La única trayectoria objetivo de producción es:

```text
Project
→ WorkflowDefinition
→ workflow.lock.json
→ run.lock.json
→ paquete autocontenido
→ AllocationController dentro de Slurm
→ Evidence / Results
```

El compilador es la autoridad para la representación bloqueada y `run prepare`
es el puente hacia el paquete remoto. Las rutas históricas pueden conservarse
como compatibilidad, prueba o evidencia, pero no pueden mantener reglas
distintas de validación, transferencia, persistencia, recuperación o éxito.
Su clasificación vigente y el plan de migración están en el roadmap y en
[`ADR-0001`](../adr/0001-single-codebase-canonical-execution-path.md).

La integración `Project → WorkflowDefinition` todavía puede requerir authoring
explícito; no se considera completa por la mera existencia de ProjectPackage.

## 7. DAG científico

Los tipos iniciales son `calculation`, `transformation`, `validation`, `sweep`,
`selection`, `checkpoint`, `postprocess`, `comparison`, `export` y `external`.
Las aristas transportan control o artefactos tipados. La expansión dinámica
debe ser declarada, determinista, acotada y materializada antes de ejecución en
`workflow.lock.json`.

### 7.1 Orden vinculante para incorporar herramientas científicas y CLI

Una herramienta científica nueva se integra de dentro hacia fuera. La CLI es
una interfaz sobre contratos canónicos, no una segunda implementación. El orden
obligatorio es:

1. estabilizar contratos versionados de regla, observación, decisión, estados,
   unidades y autoridad final;
2. representar las operaciones y expansiones como nodos y artefactos de
   `WorkflowDefinition`;
3. demostrar compilación determinista a `workflow.lock.json` y preparación por
   la ruta canónica `run prepare` a `run.lock.json` y paquete autocontenido;
4. exponer una API de aplicación independiente de la CLI para cargar, validar,
   planificar, evaluar, expandir y registrar decisiones;
5. persistir regla, hashes, observaciones, procedencia, candidato, expansión y
   decisión humana de forma verificable;
6. añadir primero comandos CLI de solo lectura, como `validate`, `show`, `plan`
   y `evaluate`;
7. añadir después edición controlada mediante preview y diff, validación previa
   y confirmación explícita; ninguna edición puede modificar silenciosamente el
   archivo fuente;
8. implementar aprobación o rechazo humano vinculados por hash a la regla, la
   evidencia y el candidato exactos;
9. verificar localmente el recorrido completo desde Project hasta decisión,
   incluyendo casos adversariales y reanudación;
10. preparar y ejecutar una aceptación HPC mínima sólo después de completar los
    pasos anteriores.

No se construye una CLI completa antes de integrar el contrato con
`WorkflowDefinition`, el compilador y `run prepare`. Los comandos no pueden
crear locks, paquetes, estados ni decisiones con semántica diferente de la API
canónica. Una regla parametrizable puede reutilizar su motor entre proyectos,
pero sus valores, tolerancias, aplicabilidad y aceptación pertenecen a una
política de proyecto bajo autoridad humana.

En convergencia adaptativa, un estado como `READY_FOR_HUMAN_REVIEW` es una
recomendación trazable, nunca una aceptación científica automática. La
propagación del parámetro a un DAG posterior exige una decisión humana
persistida y vinculada a los hashes evaluados.

### 7.2 Composición manual y ciclos científicos

La unidad de extensión científica es un fragmento de workflow con puertos de
artefacto tipados. La selección del usuario compone cero rutas implícitas: sólo
los fragmentos solicitados aparecen en el `WorkflowDefinition`. Deben poder
representarse, como mínimo, una operación aislada, una selección parcial y un
ciclo encadenado con fan-out posterior.

El compositor es agnóstico al material, al motor y a la lista futura de
análisis. No contiene nombres de proyectos, especies, pseudopotenciales,
cutoffs, grillas ni módulos científicos cerrados. Las capacidades declaran sus
entradas y salidas mediante identificadores namespaced; una conexión con tipos
incompatibles se rechaza antes de compilar.

Una relajación no exige haber ejecutado convergencia dentro del mismo ciclo.
Sí exige un perfil numérico declarado y hash-bound, cuya autoridad sea
`PROVISIONAL` o `APPROVED`. La primera opción conserva la libertad exploratoria
del investigador sin afirmar convergencia; la segunda requiere una aprobación
humana enlazada a sujeto y evidencia.

Los ciclos que atraviesan una decisión humana se materializan en locks por
etapas. Ninguna recomendación modifica un lock activo ni autoriza por sí misma
la siguiente etapa. La interfaz puede presentar el recorrido como un solo ciclo
de usuario, pero cada ejecución deriva de un lock inmutable por la ruta
canónica.

La API canónica expone la composición como una receta explícita y la CLI la
presenta mediante `workflow compose <intent> --dry-run`. El preview construye
el mismo `WorkflowDefinition` que se compilaría, no crea un lock ni autoriza
ejecución. Sólo después de la revisión humana se materializa, compila y prepara
por la ruta ordinaria.

## 8. Descubrimiento de entornos HPC

El descubrimiento sigue una promoción explícita:

```text
DISCOVER → PROBE → CANDIDATE_PROFILE → HUMAN_REVIEW → ACCEPTED_PROFILE
```

Puede observar módulos, Python, SIESTA y su versión, launchers MPI, `srun`,
`mpiexec.hydra`, partición, cuenta, QoS, rutas compartidas, scratch, variables
y capacidad multinodo. No elige módulos silenciosamente, no modifica la
sesión del usuario, no ejecuta `module purge` fuera de un shell aislado, no
supone equivalencia entre launchers y no promueve un perfil sin evidencia de
una prueba Slurm. Esta capacidad pertenece conceptualmente a la Fase 5.

## 9. Fases y criterios de cierre

### Fase 0 — Contratos del núcleo

Contratos versionados para artefactos, ejecución, eventos, plugins,
validadores, extractores, transformaciones, compatibilidad y migraciones.

**Cierre:** las capas superiores dependen de contratos públicos y un adaptador
nuevo no obliga a modificar capas independientes.

### Fase 1 — Compilador y representación canónica

DAG tipado, expansión determinista, orden topológico, artefactos,
`workflow.lock.json`, hash reproducible y migraciones de esquema.

**Cierre:** toda ejecución de producción deriva de la misma representación
bloqueada y no existen rutas paralelas con semánticas divergentes.

### Fase 2 — Experiencia inicial del investigador

Diagnóstico de entorno, inicialización e importación futura de cálculos,
validación explicable, vista previa, grafo, planificación, salida humana y
`--json`, sin exigir edición de contratos internos. Las tareas externas
requieren un mecanismo de escape explícito.

**Cierre:** un cálculo SIESTA existente puede convertirse en un workflow básico
sin reconstruir manualmente contratos internos.

### Fase 3 — Ejecutor autocontenido

Ejecución concurrente, artefactos, checkpoints, intentos, reanudación, señales,
shutdown controlado, diagnóstico y reconciliación dentro de una asignación.

**Cierre:** un paquete limpio generado por `run prepare` completa en Yoltla el
flujo padre → DM verificada → transferencia → evidencia de lectura → hijo →
reconciliación, sin daemon ni internet. Las pruebas de fallo, hash alterado, DM
ausente, interrupción y recursos no solapados forman la matriz de aceptación.

### Fase 4 — DAG adaptativo y campañas científicas

Barridos, selectores, fan-out/fan-in, propagación, recuperaciones autorizadas,
`converge_then_relax`, criterios con unidades y estabilidad consecutiva. Se
distinguen convergencia SCF, numérica y geométrica.

**Cierre:** un parámetro convergido se selecciona y propaga, la relajación
escalonada se ejecuta y el resultado final se valida con procedencia completa.

### Fase 5 — Optimización y portabilidad HPC

Perfiles, probes, Slurm, Hydra, `srun`, colocación, MPI/OpenMP futuro, memoria,
walltime, continuación entre asignaciones y backends intercambiables. Parsl no
es una decisión tomada; cualquier evaluación requiere ADR y comparación
reproducible con el backend nativo.

**Cierre:** un DAG heterogéneo utiliza correctamente una asignación real,
continúa entre asignaciones y conserva equivalencia contractual entre backends
autorizados.

### Fase 6 — Validación científica extensible

Reglas versionadas con aplicabilidad, evidencia, severidad, remediación, falsos
positivos y pruebas. La presentación diagnóstica debe distinguir `ERROR`,
`WARNING`, `REVIEW` e `INFO` sin confundirla con el estado contractual de una
decisión; cualquier cambio del vocabulario contractual existente requiere ADR,
compatibilidad y migración.

**Cierre:** la cobertura y la evidencia de campañas reales son suficientes para
el alcance declarado; una base vertical local no cierra la fase.

### Fase 7 — Resultados y publicación

Linaje, tablas, comparaciones, exportación, reportes metodológicos, métricas,
versiones, hashes, decisiones, recursos, geometrías, energía, fuerzas, SCF e
iteraciones.

**Cierre:** el investigador consulta y exporta un resultado sin reconstruir la
historia desde archivos dispersos.

### Fase 8 — Distribución y adopción

Wheel/sdist, instalación editable y limpia, `pipx` cuando proceda, CI Linux,
licencia, changelog, tutorial, esquemas públicos, compatibilidad, ejemplos y
validación por usuarios externos.

**Cierre:** investigadores externos instalan QRAFT y completan un flujo
documentado sin asistencia directa del autor. Esta fase no bloquea la
aceptación técnica remota de la Fase 3.

## 10. Invariantes

1. Ningún resultado se identifica sólo por su nombre de archivo.
2. Toda transferencia conserva hash, origen y destino.
3. La evidencia transferida y la copia de trabajo mutable son artefactos
   distintos.
4. Ninguna tarea dependiente inicia antes de validar sus padres.
5. Ninguna recuperación cambia la física sin autorización explícita.
6. La terminación normal no implica validez científica.
7. Toda decisión automática registra regla, versión, métricas y evidencia.
8. La evidencia histórica es append-only; una reclasificación es un evento.
9. El runtime remoto no mantiene procesos en login.
10. Un cambio incompatible requiere migración o nueva versión contractual.
11. Un paquete formal se vincula a locks, perfil, fuente y estado de limpieza.
12. La aceptación local nunca se presenta como aceptación de Yoltla.

## 11. Entrada al núcleo y gobernanza

Una funcionalidad entra al núcleo sólo si evita un error costoso o trabajo
repetitivo, posee un contrato independiente del motor o cluster, puede probarse
determinísticamente, conserva trazabilidad, ofrece diagnóstico y no introduce
decisiones científicas ocultas. En caso contrario permanece como plugin,
ejemplo o política de proyecto.

Cada cambio sigue especificación humana, implementación, pruebas
proporcionales al riesgo, auditoría independiente cuando corresponda, revisión
humana y commit o rechazo. Las reglas completas de Git, ADR, aceptación,
trazabilidad y releases están en
[`DEVELOPMENT_GOVERNANCE.md`](../developer/DEVELOPMENT_GOVERNANCE.md).
