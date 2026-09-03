# Inicio rápido: receta A — convergencia

Este recorrido crea una campaña de `MeshCutoff` con 80, 100 y 120 Ry. Sustituye sólo las rutas científicas y las opciones de ejecución indicadas.

```bash
mkdir my-qraft-project
cd my-qraft-project
qraft init campaign.yaml
```

Edita `campaign.yaml`: cambia `system.fdf` por tu FDF. Si tu FDF ya resuelve sus pseudopotenciales desde su propio directorio, elimina la línea de ejemplo `pseudo_manifest: pseudos/manifest.yaml`; copia allí los pseudos que el FDF requiere. Si usas un manifiesto de pseudos de tu proyecto, sustituye esa ruta por el manifiesto válido. Después:

```bash
qraft validate campaign.yaml --siesta /ruta/a/siesta
qraft plan campaign.yaml --partition local --launcher openmpi --siesta /ruta/a/siesta
qraft render campaign.yaml --output rendered
qraft run campaign.yaml --runs-root .qraft-runs \
  --partition local --nodes 1 --np 4 --cpus-per-rank 1 \
  --launcher openmpi --siesta /ruta/a/siesta
qraft status --runs-root .qraft-runs
```

`rendered/` contiene los FDF concretos. Tras una ejecución, consulta `.qraft-runs/qraft.out` primero; `campaign-result.json` contiene el resultado estructurado. Los intentos están en `.qraft-runs/work/point_XXX/attempt-XXXX/`; allí están `stdout.txt` y `stderr.txt`.

Si hubo convergencia, `status` muestra el punto seleccionado. Si no, `technical PASS` puede coexistir con `SCIENTIFIC_NOT_CONVERGED`: SIESTA funcionó, pero tus criterios no justifican elegir un valor.
