# Interrupción y reanudación: receta C

Una interrupción cooperativa deja evidencia durable y un estado `INTERRUPTED`. Comprueba primero qué ocurrió:

```bash
qraft status --runs-root .qraft-runs
qraft status --runs-root .qraft-runs --json
```

Después reanuda con las mismas opciones de ejecución:

```bash
qraft resume campaign.yaml --runs-root .qraft-runs \
  --partition local --nodes 1 --np 4 --cpus-per-rank 1 \
  --launcher openmpi --siesta /ruta/a/siesta
qraft status --runs-root .qraft-runs
```

Los attempts completados se reutilizan. Un attempt interrumpido puede conservarse como `attempt-0001` y reintentarse como `attempt-0002`. Si la interrupción ocurrió después de convergencia, la selección científica se conserva y downstream puede continuar sin recalcular puntos upstream.

Esto describe interrupciones cooperativas observadas. No prometas que un `kill -9`, un apagón o un crash externo pueda recuperar un proceso incompleto; inspecciona los attempts y usa la evidencia persistida antes de reanudar.
