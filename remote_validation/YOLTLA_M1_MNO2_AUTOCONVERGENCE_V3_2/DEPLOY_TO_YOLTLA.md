# Despliegue en Yoltla

## 1. Cancelar la versión anterior

Sólo después de confirmar que el job anterior continúa `PENDING`:

```bash
squeue -j 779795
scancel 779795
```

No cancele por número si `squeue` muestra otro propietario o si el identificador
ya fue reutilizado.

## 2. Extraer V3.2

```bash
unzip YOLTLA_M1_MNO2_AUTOCONVERGENCE_V3_2.zip
cd YOLTLA_M1_MNO2_AUTOCONVERGENCE_V3_2
module load python/3.12
python3 --version
```

## 3. Validación local en Yoltla

```bash
python3 verify_package.py
python3 scripts/automatic_campaign.py --validate-only
bash -n submit.slurm
sbatch --test-only submit.slurm
```

Los cuatro comandos deben terminar sin error. `--test-only` valida la solicitud
con el controlador Slurm, pero no reserva nodos ni ejecuta SIESTA.

## 4. Envío

```bash
sbatch submit.slurm
squeue -u "$USER"
```

El primer tiempo asignado ejecutará el preflight multinodo y el benchmark
64/128 MPI. Un fallo de preflight detiene la campaña antes de los cálculos
científicos y conserva la evidencia.

## 5. Seguimiento y reanudación

```bash
bash scripts/inspect_campaign.sh
```

Slurm puede cerrar la sesión SSH sin afectar el job. Si el walltime no alcanza,
el controlador deja `interrupted.json`; un nuevo `sbatch submit.slurm` reutiliza
únicamente intentos `PASS` con entrada idéntica y continúa desde el pendiente.

Resultados principales:

```bash
python3 -m json.tool runs/autoconvergence/final_summary.json
column -s, -t < runs/autoconvergence/traceability.csv
```
