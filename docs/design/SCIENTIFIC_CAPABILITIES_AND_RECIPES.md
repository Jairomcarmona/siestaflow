# Capacidades, recetas y API de aplicación científica

## Separación de responsabilidades

| Capa | Responsabilidad | No debe hacer |
|---|---|---|
| `ScientificIntent` | expresar qué solicita el investigador | construir comandos o aceptar ciencia |
| `WORKFLOW_BUILDER` | convertir una capacidad en tareas y puertos canónicos | ejecutar o escribir locks |
| `RECIPE` | componer capacidades en un `WorkflowDefinition` | duplicar implementaciones de capacidades |
| `WorkflowAuthoringService` | resolver registro, validar y escribir definiciones | saltarse el compilador |
| `WorkflowCompiler` | resolver DAG, artefactos y lock determinista | elegir política científica |
| `run prepare` | adaptar el lock a un paquete autocontenido | modificar el workflow |
| CLI/GUI | capturar intención y presentar resultados | contener lógica científica propia |

El registro es explícito, se congela después del bootstrap y usa contratos
versionados. No existe autodiscovery por importación ni estado global mutable.
`RunPreparer` expone además un registro inyectable de adaptadores de tarea. Los
módulos que necesiten un runtime nuevo se conectan allí sin añadir condiciones
al recorrido central; las capacidades que reutilicen el adaptador SIESTA o un
gate existente no necesitan uno nuevo.

`WorkflowComposer` combina fragmentos seleccionados por el usuario y conserva
en metadata los contratos de cada puerto y conexión. Puede materializar una
operación aislada, una selección parcial o un ciclo con fan-out sin cambiar el
compilador. Los tipos de artefacto son identificadores namespaced abiertos; no
existe una enumeración cerrada de materiales o análisis.

Un fragmento consumidor sólo puede conectarse si su contrato coincide con el
artefacto producido. Por ejemplo, un consumidor de `siestaflow.ground-state`
no acepta silenciosamente `siestaflow.relaxed-structure`. Esta validación ocurre
antes de generar el lock y se repite mediante las reglas ordinarias del DAG.

## CLI inicial

```text
siestaflow workflow recipes [--json]
siestaflow workflow recipe <recipe-id> [--json]
siestaflow workflow create <intent.json> --output <workflow.json> [--dry-run]
siestaflow workflow compose <intent.json> --output <workflow.json> [--dry-run]
siestaflow workflow validate <workflow.json>
siestaflow workflow plan <workflow.json>
siestaflow workflow compile <workflow.json> --output workflow.lock.json
siestaflow run prepare workflow.lock.json ...
```

`workflow create` no sobrescribe archivos y exige que intención, definición y
entradas permanezcan en el mismo árbol autocontenido. `--dry-run` no escribe.

`workflow compose` aplica el mismo recorrido, pero exige la receta genérica de
composición manual y sirve como vista previa del DAG antes de materializarlo.

## Composición manual de módulos

La receta `siestaflow.recipe.scientific.manual-composition` deja elegir uno o
varios builders registrados. Cada módulo declara sus propios parámetros,
recursos y metadata; el intent padre no necesita recursos de ejecución. Esta
es la interfaz para los ciclos parciales: un solo módulo, un subconjunto o una
cadena completa. No contiene nombres de materiales ni de análisis en el núcleo.

```json
{
  "schema_version": "1.0",
  "intent_id": "researcher-cycle",
  "project_id": "my-project",
  "recipe": "siestaflow.recipe.scientific.manual-composition",
  "parameters": {
    "modules": [{
      "module_id": "mesh",
      "capability": "siestaflow.siesta.mesh-evidence-evaluator",
      "parameters": {"rule": "rule.json", "observations": ["observations/001.json"]},
      "resources": {"nodes": 1, "mpi_processes": 1, "processes_per_node": 1, "cpus_per_process": 1, "walltime_seconds": 30},
      "metadata": {"authority": "HUMAN_REVIEW"}
    }]
  },
  "resources": {},
  "metadata": {"requested_by": "researcher"}
}
```

La receta resuelve exclusivamente `WORKFLOW_BUILDER` ya registrados, deriva un
hash determinista por módulo y exige que cada fragmento declare contratos de
puerto. La composición conserva `execution_authorized: false`; después se usa
la secuencia ordinaria `workflow compile` y `run prepare`.

## Relajación estructural inicial

`siestaflow.recipe.siesta.structural-relaxation` es la primera capacidad que
crea una tarea de cálculo SIESTA real. No modifica ni sintetiza FDF: recibe un
FDF científico ya declarado, una lista explícita de pseudopotenciales PSML y
recursos. Verifica antes de crear el workflow que el FDF declara
`MD.TypeOfRun CG`, `MD.NumCGSteps` positivo y un `SystemLabel` seguro. La salida
requerida queda fijada a `<SystemLabel>.XV` como
`siestaflow.relaxed-structure`.

La capacidad no declara convergencia numérica, no selecciona parámetros y no
aprueba la estructura. Conserva `execution_authorized: false`; su cálculo sólo
puede llegar a SIESTA tras compilar y usar `run prepare` con un perfil explícito.

## DOS y PDOS iniciales

`siestaflow.recipe.siesta.dos-pdos` materializa una tarea SIESTA de análisis
aislada, con un FDF y pseudopotenciales PSML declarados por el investigador. El
FDF debe declarar explícitamente `MD.TypeOfRun SinglePoint` y un único bloque
cerrado `ProjectedDensityOfStates`; sus energías ordenadas, anchura positiva,
número de puntos mayor que uno y unidad `eV` se validan como contrato de
ejecución. La receta no elige esos valores, no crea una k-grid, no reescribe el
FDF y no interpreta picos, gaps ni estados.

La salida canónica contiene dos artefactos requeridos, ligados por hash al
paquete: `<SystemLabel>.DOS` (`siestaflow.total-density-of-states`) y
`<SystemLabel>.PDOS` (`siestaflow.projected-density-of-states`). Así se puede
ejecutar un análisis aislado desde CLI hoy, y un consumidor futuro podrá enlazar
estos artefactos a un módulo de tabla, gráfica o comparación sin alterar el
motor ni nombrar un material en el núcleo.

## Aprobación y propagación de convergencia

Una recomendación `READY_FOR_HUMAN_REVIEW` no altera el lock que produjo la
evidencia. El investigador persiste primero una decisión hash-bound y después,
sólo si la decisión es `APPROVE`, materializa un perfil numérico inmutable:

```text
reporte de convergencia exacto
  -> scientific decide (APPROVE o REJECT)
  -> scientific profile (sólo APPROVE)
  -> nuevo intent converge-then-relax
  -> workflow.lock.json nuevo -> run prepare
```

```text
siestaflow scientific decide report.json --approval-id mesh-approval-01 \
  --decision APPROVE --actor researcher --decided-at 2026-08-02T00:00:00Z \
  --output mesh-approval.json
siestaflow scientific profile report.json --approval mesh-approval.json \
  --profile-id mesh-200-ry --output mesh-profile.json
```

Los contratos persisten la selección exacta y los hashes del candidato, reporte
y decisión. La receta `siestaflow.recipe.siesta.converge-then-relax` recibe por
cada parámetro el perfil, la decisión y el reporte. Rechaza una decisión
`REJECT`, evidencia alterada, hashes no coincidentes o un FDF cuyo
`Mesh.Cutoff` o `kgrid.MonkhorstPack` no coincide con el perfil aprobado. No
reescribe el FDF ni autoriza la ejecución; el perfil y su evidencia quedan como
entradas del nuevo lock autocontenido.

## Intents de evaluación de convergencia

```json
{
  "schema_version": "1.0",
  "intent_id": "mesh-evidence-local",
  "project_id": "my-project",
  "recipe": "siestaflow.recipe.siesta.mesh-evidence-evaluation",
  "parameters": {
    "rule": "rule.json",
    "observations": ["observations/001.json", "observations/002.json"]
  },
  "resources": {
    "nodes": 1,
    "mpi_processes": 1,
    "processes_per_node": 1,
    "cpus_per_process": 1,
    "walltime_seconds": 30
  },
  "metadata": {"authority": "HUMAN_REVIEW"}
}
```

La regla y observaciones deben ser JSON porque se copian al runtime mínimo sin
dependencias opcionales. El compilador añade sus hashes como artefactos externos.

La segunda receta registrada es
`siestaflow.recipe.siesta.kgrid-evidence-evaluation`. Conserva la misma
interfaz de intent, recipe, lock y paquete, pero su regla expresa una serie de
grillas Monkhorst-Pack con desplazamientos invariantes y refinamiento estricto.
Evalúa energía por átomo, fuerzas, SCF, firma magnética, identidad inmutable y
la igualdad entre grilla solicitada y usada. No aplica la prueba eggbox, que es
específica de la malla real espacial.

## Productor de observaciones reales

`siestaflow.recipe.siesta.observation-production` registra el paso previo a
ambos evaluadores. Su capacidad no ejecuta SIESTA: procesa `FDF`, `stdout`,
`FORCE_STRESS` y el manifiesto de pseudopotenciales ya producidos. Exige
evidencia de energía final, malla efectiva, SCF convergido, terminación normal
y fuerzas por átomo; cualquier ausencia bloquea la observación. Su salida es un
artefacto `siestaflow.mesh-observation` o `siestaflow.kgrid-observation`,
enlazado por hashes al input invariante.

## Extensión futura

Una implementación nueva debe aportar descriptores, builder, recipe cuando
proceda, adaptador de `run prepare` únicamente si introduce un tipo de ejecución
nuevo, y pruebas de contrato. El objetivo es que:

```text
k-grid = segundo builder/política validado reutilizando la misma API y runtime
DOS/PDOS/bandas = capacidades consumidoras de artefactos electrónicos
fonones/óptica = plugins que declaran sus propios puertos y validadores
```

Antes de afirmar generalidad deben pasar tres cortes diferentes: Mesh como
estudio adaptativo, k-grid como segundo eje y DOS o bandas como consumidor.
