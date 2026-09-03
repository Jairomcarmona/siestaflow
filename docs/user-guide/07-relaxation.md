# Relajación: receta B

La relajación downstream sólo empieza después de una selección válida de convergencia. Es una relajación SIESTA de **celda fija** que reutiliza automáticamente el `MeshCutoff` seleccionado.

Actívala en el YAML:

```yaml
relaxation:
  enabled: true
  type: CG
  steps: 4
  max_force: 0.05
  unit: eV/Ang
```

`type: CG` se materializa para SIESTA como el tipo de corrida de relajación. `steps` limita los pasos y `max_force` es el umbral de fuerza en `eV/Ang`. La celda no se relaja.

Ejecuta la misma receta de [Inicio rápido](02-quickstart.md). Tras una selección, encuentra:

```text
.qraft-runs/downstream/rendered/input.fdf
.qraft-runs/downstream/relaxation/work/relax/attempt-0001/
  STRUCT_OUT
  relaxed-geometry.json
  stdout.txt
  stderr.txt
```

`relaxed-geometry.json` es el artefacto de geometría final de QRAFT; deriva de la salida real de SIESTA. Si la relajación terminó técnicamente bien pero no alcanza el umbral de fuerza en los pasos configurados, `technical PASS` y un resultado científico no convergente siguen siendo informativos y válidos.
