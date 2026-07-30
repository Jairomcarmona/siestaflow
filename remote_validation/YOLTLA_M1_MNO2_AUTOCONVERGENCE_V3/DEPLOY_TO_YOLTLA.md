# Despliegue en Yoltla

## 1. Copiar y extraer

Copie el ZIP completo a Yoltla y extráigalo en un directorio de trabajo de
LUSTRE. Entre en la carpeta:

```bash
unzip YOLTLA_M1_MNO2_AUTOCONVERGENCE_V3.zip
cd YOLTLA_M1_MNO2_AUTOCONVERGENCE_V3
```

## 2. Verificación sin cálculo

```bash
python3 verify_package.py
python3 scripts/automatic_campaign.py --validate-only
bash -n submit.slurm
```

Los tres comandos deben terminar sin error. Esta verificación comprueba
estructura, hashes, pseudopotenciales, FDF base y solicitud exacta de 128
tareas; no ejecuta SIESTA.

## 3. Envío único

```bash
sbatch submit.slurm
```

No ejecute el script mediante `nohup` y no mantenga una sesión SSH abierta. El
trabajo y el controlador viven dentro de Slurm.

## 4. Seguimiento

```bash
squeue -u "$USER"
bash scripts/inspect_campaign.sh
```

Las salidas de Slurm se escriben como `OUT.M1_MnO2_AutoConv.<jobid>` y
`ERROR.M1_MnO2_AutoConv.<jobid>`.

## 5. Reanudación

Si Slurm envía `SIGUSR1` antes del límite, el intento activo queda marcado como
interrumpido y las etapas terminadas permanecen intactas. Para continuar:

```bash
sbatch submit.slurm
```

El controlador reutiliza únicamente intentos `PASS` cuyo hash de entrada
coincide. Nunca sobrescribe los intentos anteriores.

## 6. Resultado final

Revisar:

```bash
python3 -m json.tool runs/autoconvergence/final_summary.json
column -s, -t < runs/autoconvergence/traceability.csv
```

`PASS_ROBUST` significa que FM/stripe-AFM seleccionaron el mismo orden en
Ueff=3.8 y 4.0 eV. `COMPLETED_REVIEW_REQUIRED` significa que todas las pruebas
terminaron, pero existe cruce o degeneración magnética que no debe resolverse
automáticamente.
