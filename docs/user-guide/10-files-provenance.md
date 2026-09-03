# Archivos y trazabilidad

Una campaña típica genera este árbol (puede haber archivos adicionales del engine):

```text
.qraft-runs/
  rendered/                  # FDF concretos por punto
  work/point_001/attempt-0001/
    input.fdf
    stdout.txt
    stderr.txt
    attempt.json
  evidence/
  state/                     # estado durable de workflow
  results/
  downstream/                # sólo si relaxation está habilitada
  campaign-result.json
  qraft.out
```

La cadena de evidencia es:

```text
campaign.yaml → rendered FDF → attempt → salida SIESTA
→ evidencia de convergencia → selección → FDF downstream
→ STRUCT_OUT → relaxed-geometry.json
```

`state/` y los manifiestos de attempt son el estado autoritativo para QRAFT. `qraft.out` es la lectura humana. Los FDF renderizados permiten revisar lo que se entregó a SIESTA. Conserva el runs-root completo si necesitas reproducir, inspeccionar o reanudar una campaña.
