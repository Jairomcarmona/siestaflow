# Tutorial canónico de CLI

Este tutorial describe una ruta completa, reproducible y segura para preparar
una campaña SIESTA. La CLI prepara, verifica y registra evidencia; nunca envía
un trabajo automáticamente. La decisión científica -- material, funcional,
espín, pseudopotenciales, parámetros numéricos y criterios de aceptación --
permanece explícita en los archivos de intención e input del investigador.

## 1. Preparar un directorio de trabajo

Trabaje fuera del código fuente con un directorio que contenga la intención,
los FDF y los pseudopotenciales declarados por la receta elegida. Las rutas de
inputs deben ser relativas a ese directorio.

```text
my-study/
  intent.json
  inputs/
  pseudos/
  execution-profile.json
```

Desde un checkout de QRAFT, use el módulo de Python para evitar depender
de que exista un comando global instalado:

```powershell
Set-Location C:\path\to\qraft
$env:PYTHONPATH = 'src'
python -m qraft.cli workflow recipes --json
```

Seleccione una receta y consulte su contrato antes de construir una intención:

```powershell
python -m qraft.cli workflow recipe RECIPE_ID --json
```

La receta declara qué parámetros y archivos son obligatorios. No copie nombres
de materiales o valores de otro estudio: declare los propios en `intent.json`.

## 2. Materializar y revisar el workflow

```powershell
python -m qraft.cli workflow create intent.json --output workflow.json --json
python -m qraft.cli workflow preflight workflow.json --json
python -m qraft.cli workflow plan workflow.json --json
python -m qraft.cli workflow graph workflow.json --format mermaid
python -m qraft.cli workflow compile workflow.json --output workflow.lock.json --json
```

Deténgase si `preflight` no devuelve `PASS`. `workflow.lock.json` inmoviliza el
DAG y las entradas externas por SHA-256; no contiene una autorización para
ejecutar ni debe editarse manualmente.

## 3. Capturar capacidad Slurm viva

En el cluster, capture sólo comandos de lectura. Para Yoltla, la capacidad por
variante se obtiene además con `sjstat -c`:

```bash
mkdir -p phase-live/raw
date -u +%Y-%m-%dT%H:%M:%SZ > phase-live/raw/observed-at.txt
sinfo -h -o '%P|%a|%l|%D|%c|%m' > phase-live/raw/sinfo.txt
scontrol show partition -o > phase-live/raw/scontrol-partitions.txt
scontrol show node -o > phase-live/raw/scontrol-nodes.txt
sacctmgr -n -P show assoc user="$USER" format=Account,Partition,QOS > phase-live/raw/sacctmgr-assoc.txt
sjstat -c > phase-live/raw/sjstat-c.txt
tar -czf phase-live-raw.tar.gz -C phase-live raw
```

Transfiera el archivo a su equipo y conviértalo en snapshot local:

```powershell
$raw = 'C:\path\to\phase-live\raw'
python -m qraft.cli run snapshot-import `
  --cluster-id CLUSTER_ID `
  --output cluster-snapshot.json `
  --sinfo "$raw\sinfo.txt" `
  --scontrol-partitions "$raw\scontrol-partitions.txt" `
  --scontrol-nodes "$raw\scontrol-nodes.txt" `
  --sacctmgr "$raw\sacctmgr-assoc.txt" `
  --sjstat "$raw\sjstat-c.txt" `
  --observed-at (Get-Content -Raw "$raw\observed-at.txt").Trim() `
  --json
```

No use catálogos históricos para representar disponibilidad viva.

## 4. Revisar y confirmar recursos

El perfil de ejecución contiene launcher, módulos, cuenta, QoS, memoria y
política de apagado; no modifica el workflow científico.

```powershell
python -m qraft.cli run candidates `
  --workflow workflow.lock.json `
  --profile execution-profile.json `
  --snapshot cluster-snapshot.json `
  --json
```

Seleccione sólo un candidato `COMPATIBLE` que satisfaga nodos, ranks, memoria,
cuenta, QoS, tiempo y rasgos de hardware. Si el build de SIESTA requiere una
arquitectura comprobada, guarde su evidencia estructurada de compatibilidad y
realice una resolución manual validada:

```powershell
python -m qraft.cli run prepare workflow.lock.json `
  --source-root . `
  --profile execution-profile.json `
  --snapshot cluster-snapshot.json `
  --compatibility-evidence siesta-compatibility.json `
  --partition PARTITION `
  --nodes NODES `
  --ranks-per-node RANKS_PER_NODE `
  --account ACCOUNT `
  --qos QOS `
  --walltime HH:MM:SS `
  --required-feature FEATURE `
  --confirm `
  --output packages `
  --run-id RUN_ID `
  --json
```

`--confirm` registra una decisión humana de recursos; no es una decisión
científica. El preparador falla si la capacidad, autorización, rasgo o tiempo
de una tarea no caben en la asignación declarada.

## 5. Verificar y transferir el paquete

El resultado es `packages/RUN_ID/` y `packages/RUN_ID.zip`. Antes de subirlo:

```powershell
python packages/RUN_ID/verify_package.py
bash -n packages/RUN_ID/submit.slurm
bash -n packages/RUN_ID/progress.sh
python -m zipfile -t packages/RUN_ID.zip
```

En el cluster, compare el SHA-256 del ZIP con el valor emitido por `run prepare`.
Extraiga en un directorio nuevo y entre explícitamente al directorio del
paquete antes de enviar Slurm:

```bash
unzip -q RUN_ID.zip -d RUN_ID-clean
cd RUN_ID-clean/RUN_ID
module load python/3.12
python3 verify_package.py
bash -n submit.slurm
sbatch --test-only submit.slurm
sbatch submit.slurm
```

Ejecutar `sbatch` con una ruta absoluta desde una carpeta padre cambia
`SLURM_SUBMIT_DIR` y puede impedir que el script encuentre `verify_package.py`.
Por eso el `cd` al directorio del paquete es obligatorio.

## 6. Observar, verificar y exportar

En el cluster:

```bash
bash progress.sh
squeue -u "$USER"
sacct -j JOB_ID --format=JobID,State,ExitCode,Elapsed,NodeList
```

Cuando el job termine, revise `results/campaign_summary.json`, los manifiestos
de intento en `work/TASK_ID/attempt-XXXX/result_manifest.json` y los logs
`OUT.*` y `ERROR.*`. Para una dependencia de DM, el consumidor debe registrar
`dm_read_succeeded: true`; la terminación normal sola no demuestra esa lectura.

Después de transferir el paquete completado a un equipo con el checkout de
QRAFT, exporte tablas sin interpretación científica:

```powershell
python -m qraft.cli results bands COMPLETED_PACKAGE --output exports/bands --json
python -m qraft.cli results dos-pdos COMPLETED_PACKAGE --output exports/dos-pdos --json
python -m qraft.cli results optics COMPLETED_PACKAGE --output exports/optics --json
```

## Límites del tutorial

Este recorrido valida procedencia, ejecución y datos exportados. No sustituye
una regla científica de convergencia, una revisión de geometría o una
interpretación de bandas, DOS/PDOS u óptica. Para recuperación controlada use
`run inspect`, `run status` y `run resume`; para la semántica detallada vea la
referencia CLI y el runbook del cluster.
