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

## CLI inicial

```text
siestaflow workflow recipes [--json]
siestaflow workflow recipe <recipe-id> [--json]
siestaflow workflow create <intent.json> --output <workflow.json> [--dry-run]
siestaflow workflow validate <workflow.json>
siestaflow workflow plan <workflow.json>
siestaflow workflow compile <workflow.json> --output workflow.lock.json
siestaflow run prepare workflow.lock.json ...
```

`workflow create` no sobrescribe archivos y exige que intención, definición y
entradas permanezcan en el mismo árbol autocontenido. `--dry-run` no escribe.

## Intent de evaluación Mesh

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

## Extensión futura

Una implementación nueva debe aportar descriptores, builder, recipe cuando
proceda, adaptador de `run prepare` únicamente si introduce un tipo de ejecución
nuevo, y pruebas de contrato. El objetivo es que:

```text
k-grid = nuevo builder/política reutilizando ParameterStudy
DOS/PDOS/bandas = capacidades consumidoras de artefactos electrónicos
fonones/óptica = plugins que declaran sus propios puertos y validadores
```

Antes de afirmar generalidad deben pasar tres cortes diferentes: Mesh como
estudio adaptativo, k-grid como segundo eje y DOS o bandas como consumidor.
