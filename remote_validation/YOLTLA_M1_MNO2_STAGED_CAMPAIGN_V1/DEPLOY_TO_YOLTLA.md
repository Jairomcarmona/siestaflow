# Despliegue controlado en Yoltla

## 1. Transferir y verificar

Desde el equipo local se transfiere el ZIP por el canal autorizado. En Yoltla:

```bash
unzip YOLTLA_M1_MNO2_STAGED_CAMPAIGN_V1.zip
cd YOLTLA_M1_MNO2_STAGED_CAMPAIGN_V1
python3 verify_package.py
chmod u+x scripts/*.sh scripts/*.py
```

El resultado local esperado es:

```text
YOLTLA_M1_PACKAGE_VERIFIED
REMOTE_SUBMISSION_NOT_PERFORMED
```

## 2. Caracterizar el perfil largo

La plantilla de 80 CPU/48 h no se debe activar por memoria. Capture primero
evidencia actual:

```bash
./scripts/capture_site_evidence.sh
```

Revise `site/evidence/<fecha>/`. Cree después
`profiles/yoltla_production.json` a partir de la plantilla, reemplace todos los
`CONFIGURE_FROM_REMOTE_EVIDENCE`, cambie `profile_status` únicamente a
`VERIFIED_FOR_PRODUCTION` y registre en `evidence_sha256` cada archivo usado
para justificar partición, cuenta, QoS, nodos, memoria, límite de tiempo,
ejecutable y lanzador. El guardián vuelve a calcular esos hashes.

La prueba técnica ya observada sólo sustenta 20 CPU/1 h; no prueba la cola
larga.

## 3. Importar PSML

Copie `Mn.psml` y `O.psml` a `external/pseudopotentials/`. Verifique:

```bash
python3 scripts/campaignctl.py verify --with-external
```

## 4. Firmar la compuerta de la fase

Copie la plantilla correspondiente de `gates/templates/` a
`gates/decisions/`, cambie `decision` a `ACCEPTED`, registre responsable,
fecha y los hashes SHA-256 de la evidencia relativa al directorio del paquete.
No se incluye ninguna aceptación prefabricada.

## 5. Materializar sin enviar

```bash
python3 scripts/campaignctl.py prepare \
  --phase 01_sanity \
  --profile profiles/yoltla_production.json
```

Para la malla, después de F2:

```bash
python3 scripts/campaignctl.py prepare \
  --phase 03a_mesh \
  --profile profiles/yoltla_production.json
```

El materializador crea directorios aislados en `generated/<fase>/`, un FDF por
tarea, hashes de cada entrada, `controller.json`, `launch_guard.json` y
`submit.slurm`.

## 6. Preflight y envío humano

```bash
./scripts/preflight.sh 01_sanity profiles/yoltla_production.json
cd generated/01_sanity
JOB_ID=$(sbatch --parsable submit.slurm)
echo "$JOB_ID"
../../scripts/inspect_job.sh "$JOB_ID"
```

El paquete no ejecuta esa orden por sí mismo. `sbatch --test-only` forma parte
del preflight y no crea un trabajo.

## 7. Reanudación

Espere a que el trabajo anterior sea terminal en `sacct`. Si terminó por
walltime y el resumen indica tareas incompletas, vuelva a ejecutar manualmente
el mismo `submit.slurm`. El controlador valida el estado y no repite tareas
completadas cuyos hashes y manifiestos aún sean válidos.

No borre `state/`, `work/`, `evidence/` ni `results/`.

