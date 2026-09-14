# Slurm y HPC

QRAFT ejecuta SIESTA dentro de una asignación Slurm existente. No selecciona
una cola a partir de su nombre y el flujo instalado de un FDF no llama a
`sbatch`. La partición y la geometría del perfil deben coincidir exactamente
con los recursos concedidos por `salloc` o por las directivas `#SBATCH`.

## 1. Instalar una copia del repositorio

Haz la instalación en un sistema de archivos visible desde los nodos de
cómputo. Sustituye los módulos por los aprobados en tu centro:

```bash
git clone https://github.com/Jairomcarmona/siestaflow.git
cd siestaflow
module purge
module load python/3.12
module load siesta/5.4.2
module load MPI_APROBADO
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
qraft --version
```

Si los nodos no tienen acceso a Internet, instala previamente desde el
wheelhouse de tu centro. Python 3.11 o posterior es obligatorio; SIESTA, MPI y
Slurm son dependencias externas y no se incluyen en QRAFT.

Guarda un perfil en `.qraft/profiles/slurm-srun.toml`, siguiendo
[Perfiles de ejecución](../user/profiles.md), y edita partición, nodos, rangos,
CPU por rango, tiempo y ejecutable con valores reales del sitio. Valídalo antes
de solicitar recursos:

```bash
qraft setup profile validate slurm-srun
qraft setup config --profile slurm-srun
```

`module_commands` se conserva como documentación del despliegue, pero el flujo
instalado no ejecuta comandos de módulo. Activa los módulos y el entorno virtual
en la shell o en el script batch.

## 2. Ejecución interactiva con `salloc`

Este ejemplo corresponde a un perfil con 2 nodos, 32 rangos por nodo y una CPU
por rango. Añade `--account` y `--qos` si tu centro los exige:

```bash
salloc --partition=compute --nodes=2 --ntasks=64 \
  --ntasks-per-node=32 --cpus-per-task=1 --time=01:00:00

# Ya dentro de la asignación:
cd /ruta/compartida/siestaflow
module purge
module load python/3.12
module load siesta/5.4.2
module load MPI_APROBADO
source .venv/bin/activate

RUNS_ROOT="${SCRATCH}/qraft/${USER}/calculo-001"
qraft setup env --profile slurm-srun
qraft check calc.fdf --profile slurm-srun --runs-root "$RUNS_ROOT"
qraft inspect plan calc.fdf --profile slurm-srun
qraft run calc.fdf --profile slurm-srun --runs-root "$RUNS_ROOT"
qraft status --runs-root "$RUNS_ROOT"
qraft results --runs-root "$RUNS_ROOT"
```

El FDF, sus archivos incluidos y los pseudopotenciales deben existir en el
filesystem compartido. Usa un `RUNS_ROOT` nuevo y estable para cada cálculo;
debe sobrevivir al final del job para permitir inspección y reanudación.

QRAFT valida antes de lanzar que `SLURM_NNODES`, `SLURM_NTASKS`,
`SLURM_CPUS_PER_TASK` y `SLURM_TASKS_PER_NODE` coincidan con el perfil. También
resuelve los hosts concedidos desde `SLURM_JOB_NODELIST`. Una diferencia bloquea
la ejecución antes de iniciar SIESTA.

## 3. Ejecución batch con `sbatch`

Crea previamente `logs/` y guarda lo siguiente como `submit-qraft.slurm`. El
script pide la asignación; QRAFT usa `srun` dentro de ella:

```bash
#!/usr/bin/env bash
#SBATCH --job-name=qraft-calc-001
#SBATCH --partition=compute
#SBATCH --nodes=2
#SBATCH --ntasks=64
#SBATCH --ntasks-per-node=32
#SBATCH --cpus-per-task=1
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x-%j.out
#SBATCH --error=logs/%x-%j.err

set -euo pipefail
cd "$SLURM_SUBMIT_DIR"

module purge
module load python/3.12
module load siesta/5.4.2
module load MPI_APROBADO
source .venv/bin/activate

: "${SCRATCH:?SCRATCH no esta definido}"
RUNS_ROOT="${SCRATCH}/qraft/${USER}/calculo-001"

qraft setup profile validate slurm-srun
qraft setup env --profile slurm-srun
qraft check calc.fdf --profile slurm-srun --runs-root "$RUNS_ROOT"
qraft inspect plan calc.fdf --profile slurm-srun
qraft run calc.fdf --profile slurm-srun --runs-root "$RUNS_ROOT"
qraft status --runs-root "$RUNS_ROOT"
qraft results --runs-root "$RUNS_ROOT"
```

```bash
mkdir -p logs
sbatch submit-qraft.slurm
squeue -u "$USER"
```

Conserva los archivos `logs/%x-%j.*` junto con el `RUNS_ROOT`; los primeros son
evidencia del scheduler y el segundo contiene la evidencia propia de QRAFT.

## 4. Reanudar en una asignación nueva

Solicita otra asignación con la misma geometría, carga el mismo entorno y usa el
mismo `RUNS_ROOT`:

```bash
qraft status --runs-root "$RUNS_ROOT"
qraft resume --runs-root "$RUNS_ROOT"
qraft status --runs-root "$RUNS_ROOT"
qraft results --runs-root "$RUNS_ROOT"
```

`resume` carga `session.json` y reutiliza los intentos que ya tienen evidencia
válida. No borres ni edites los directorios `attempt-*` para forzar una
repetición.

## Límites operativos

- `qraft setup profile validate` comprueba la estructura; `check` y `run`
  vuelven a resolver el ejecutable, launcher y entorno efectivos.
- Un launcher `srun` o Hydra requiere una asignación Slurm activa. Para Hydra,
  además deben funcionar el bootstrap configurado y la conectividad entre los
  hosts concedidos.
- `COMPLETED` y una validación técnica `PASS` prueban la mecánica registrada, no
  la validez física, la convergencia científica ni la calidad de los
  pseudopotenciales.
- Consulta al administrador para partición, cuenta, QoS, memoria, límites y
  política de módulos; `squeue` sólo muestra el estado actual del scheduler.
