# Despliegue controlado en Yoltla

## 1. Verificar el paquete

```bash
unzip YOLTLA_M1_MNO2_STAGED_CAMPAIGN_V2.zip
cd YOLTLA_M1_MNO2_STAGED_CAMPAIGN_V2
python3 verify_package.py
python3 scripts/campaignctl.py verify --with-external
```

Los PSML ya están incluidos. No deben sustituirse:

```text
Mn.psml  0b97ccd71456e4a7b28316f78ddb30bb1f6a82d9aba386c7fde78090d31c0dc6
O.psml   224ded5c59176d9bcb76d19b7a4a68a48d5dffabf8b262f64d5760250e87c35e
```

## 2. Capturar evidencia actual

```bash
./scripts/capture_site_evidence.sh
```

El script ejecuta comandos de lectura y `sbatch --test-only`; no envía un
trabajo. Revise todos los archivos bajo `site/evidence/<fecha>/`.

## 3. Construir y aceptar el perfil mutable

```bash
python3 scripts/profilectl.py build \
  --evidence site/evidence/<fecha> \
  --template profiles/yoltla_qz2d_128p.template.json \
  --output site/profiles/yoltla_qz2d_128p_80c_48h.json

python3 scripts/profilectl.py approve \
  site/profiles/yoltla_qz2d_128p_80c_48h.json \
  --accepted-by "<responsable>" \
  --layout dual_40
```

`dual_40` es una hipótesis inicial, no una conclusión de escalamiento. Si la
calibración cambia la decisión, reconstruya/apruebe el perfil y vuelva a
materializar; el SHA-256 del perfil en `launch_guard.json` impide reutilizar
una preparación anterior.

La política de memoria es `partition_default`: el script omite `--mem`.
Confirme en la evidencia que esto mantiene la semántica `ExclusiveUser` de
qz2d-128p. Si Yoltla exige memoria explícita, cambie la plantilla en una
revisión posterior auditada, no el perfil silenciosamente.

## 4. Crear F0 sin aceptación prefabricada

```bash
python3 scripts/gatectl.py draft-f0 \
  --profile site/profiles/yoltla_qz2d_128p_80c_48h.json \
  --output-directory "$PWD/generated" \
  --scope "00_scaling_calibration"

# Revisar gates/decisions/F0_EXECUTION_AUTHORIZATION.json
python3 scripts/gatectl.py accept \
  --gate F0_EXECUTION_AUTHORIZATION \
  --accepted-by "<responsable>"
```

La aceptación liga FDF, PSML, perfil, versión requerida, backend/preflight,
salida y alcance. Para ejecutar `01_sanity_03a_mesh` también debe existir una
decisión explícita `RESOURCE_LAYOUT_ACCEPTED`.

## 5. Materializar sin enviar

```bash
python3 scripts/campaignctl.py prepare \
  --phase-or-bundle 01_sanity_03a_mesh \
  --profile site/profiles/yoltla_qz2d_128p_80c_48h.json

./scripts/preflight.sh \
  01_sanity_03a_mesh \
  site/profiles/yoltla_qz2d_128p_80c_48h.json
```

El preflight de login carga exactamente `siesta/5.4.2`, repite las
verificaciones y ejecuta `sbatch --test-only`.

## 6. Envío exclusivamente manual

```bash
cd generated/01_sanity_03a_mesh
sbatch --test-only submit.slurm

# Solo después de revisar todo:
sbatch submit.slurm
```

Dentro de la asignación, `submit.slurm` vuelve a comprobar integridad y hashes,
ejecuta el preflight remoto en ambos nodos y solo entonces inicia el
controlador. El preflight MPI fallido detiene la campaña antes de leer un FDF.

## 7. Reanudación

Si el trabajo termina por margen de tiempo, confirme su estado terminal con
`sacct` y vuelva a enviar manualmente el mismo `submit.slurm`. No borre
`state/`, `work/`, `evidence/` ni `results/`.

Malla y k-grid se mantienen en tickets distintos porque la malla debe ser
seleccionada científicamente por una persona. No se construye un k-grid con un
“ganador” automático.
