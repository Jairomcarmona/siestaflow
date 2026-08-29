# ADR-0004 — Contrato live Slurm a DerivedPlacement

Estado: `Accepted`
Fecha: `2026-08-29`

## Contexto

La geometría de una ejecución HPC es administrativa y mutable. Para una nueva
ejecución, la autoridad es el scheduler vivo y la asociación observada del
usuario, no el nombre de una cola, un perfil almacenado ni un snapshot
histórico. La elección de la partición sigue siendo una decisión explícita del
investigador.

## Decisión

El contrato vinculante de colocación es:

```text
LIVE Slurm policy/capabilities
+ UserAssociation
+ ResourceRequest
+ explicit human selection
↓
DerivedPlacement
↓
ExecutionSpec
↓
SBATCH request
↓
ActualAllocation
↓
LauncherPlacement
↓
engine execution
```

Las fuentes live normales son `sinfo`, `sinfo -N`, `scontrol show partition` y
`sacctmgr show assoc`. Se consulta `scontrol show config` cuando sea necesario
interpretar CPU, core o thread. `squeue` es sólo informativo: no es autoridad
para capacidad, autorización ni predicción de espera.

La política y las capacidades live de Slurm son autoridad para selecciones
nuevas. El investigador elige `partition`; si `MinNodes != MaxNodes`, también
proporciona `nodes` explícitamente. No se infiere ninguna política a partir de
nombres o sufijos de cola. No existen tablas `partition → resources` como
autoridad de producción.

`PartitionPolicy`, `NodeCapabilities`, `UserAssociation` y `ResourceRequest`
producen `DerivedPlacement`. Para una partición de tamaño fijo se aplica la
política `MAXIMUM_LEGAL_PLACEMENT_FIXED_PARTITION`; para un rango de nodos se
falla cerrado hasta recibir la selección humana de nodos. Una partición nueva
nunca vista debe poder utilizarse sin modificar código cuando Slurm entregue
evidencia suficiente.

Antes de derivar la geometría se comprueba la homogeneidad y capacidad segura
de los nodos elegibles. Si esa propiedad no puede demostrarse con la evidencia
live, la resolución falla cerrada. Los invariantes son:

- `ntasks == nodes * tasks_per_node`.
- `tasks_per_node * cpus_per_task <= cpus_per_node`.
- `DerivedPlacement` es la fuente única para `SBATCH` y todos los launchers.
- El renderer del scheduler y los adaptadores de launcher no recalculan la
  geometría.

`ExecutionSpec` refleja la partición, recursos y launcher reales, pero
`ScientificIdentity` permanece estable. Después de que Slurm conceda la
asignación, se verifica `ActualAllocation` contra `DerivedPlacement` antes de
ejecutar el engine. También se verifica `LauncherPlacement`: ranks totales,
hosts y ranks por host cuando aplique. Cualquier mismatch entre POLICY,
REQUEST, ALLOCATION o LAUNCHER aborta antes de SIESTA.

Después de discovery y la selección humana se persiste un snapshot como
provenance reproducible. Los snapshots históricos nunca son autoridad para el
estado actual ni para nuevas selecciones.

## Consecuencias

La selección humana es explícita, evidence-bound y separada de la identidad
científica. Las capas posteriores consumen la geometría derivada sin volver a
interpretar particiones ni capacidades. La validación previa al engine detecta
divergencias entre la política observada, el request construido, la asignación
real y el launcher efectivo.

## Compatibilidad

Los snapshots y perfiles históricos siguen siendo evidencia reproducible y
pueden conservarse como provenance. No adquieren autoridad operativa para una
nueva ejecución. Este ADR no modifica `ScientificIdentity`; hace explícita la
autoridad administrativa que debe quedar representada en `ExecutionSpec`.

## Referencias

- [ADR-0002](0002-flexible-slurm-resource-resolution.md)
- [ADR-0001](0001-single-codebase-canonical-execution-path.md)
