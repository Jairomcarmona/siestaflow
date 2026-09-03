# Ejecutar campañas

La ejecución pública empieza con `qraft run`:

```bash
qraft run campaign.yaml --runs-root .qraft-runs \
  --partition local --nodes 1 --np 4 --cpus-per-rank 1 \
  --launcher openmpi --siesta /ruta/a/siesta
```

En orden, QRAFT hace preflight, genera variantes de FDF, crea intentos, ejecuta SIESTA, extrae métricas, decide la convergencia y, si está habilitada, inicia relajación. `--runs-root` es el directorio persistente de la campaña; usa uno nuevo para una campaña independiente.

Un **attempt** es una ejecución concreta de un punto. Por ejemplo, `work/point_002/attempt-0001/` contiene exactamente los archivos de esa ejecución. No borres attempts para “forzar” una repetición: `qraft resume` y un re-run reutilizan evidencia válida y crean un nuevo intento sólo cuando corresponde.

Ejemplos de launcher:

```bash
# proceso local único
qraft run campaign.yaml --partition local --launcher direct --siesta /ruta/a/siesta

# MPI local
qraft run campaign.yaml --partition local --nodes 1 --np 4 \
  --launcher openmpi --siesta /ruta/a/siesta
```

Para Slurm usa el procedimiento del sitio y [Slurm y HPC](11-slurm-hpc.md); no inventes una partición ni una geometría MPI.
