# `campaign.yaml`

`qraft init campaign.yaml` crea el template público. Sus campos científicos son:

| Campo | Obligatorio | Significado |
|---|---:|---|
| `schema_version` | Sí | Versión del formato; usa `"1.0"`. |
| `campaign_id` | Sí | Nombre legible de la campaña. |
| `engine` | Sí | `siesta`. |
| `protocol` | Sí | `convergence`. |
| `system.fdf` | Sí | FDF base, relativo o absoluto. |
| `system.pseudo_manifest` | No | Manifiesto de pseudopotenciales; el template incluye una ruta de ejemplo. Elimínalo si tu FDF resuelve los pseudos directamente desde su directorio. |
| `parameters.mesh_cutoff.values` | Sí | Lista de valores en Ry. |
| `parameters.basis_size` | Sí | Base SIESTA, por ejemplo `DZP`. |
| `criterion.metric` | Sí | `energy_per_atom`. |
| `criterion.delta` | Sí | Tolerancia, en la unidad indicada. |
| `criterion.consecutive` | Sí | Número de diferencias consecutivas que deben cumplir. |

Ejemplo de barrido:

```yaml
parameters:
  mesh_cutoff:
    mode: scan
    values: [80, 100, 120]
    unit: Ry
criterion:
  metric: energy_per_atom
  delta: 0.01
  unit: eV
  consecutive: 1
```

No pongas rutas de un equipo ajeno en el YAML. La elección de SIESTA, launcher, partición y recursos pertenece a un perfil o a la línea de comandos. Un YAML mal indentado, una lista sustituida por texto o un FDF/pseudo inexistente se bloquean en preflight.

La sección `relaxation` es opcional: `enabled: false` desactiva downstream. Para activarla, consulta [Relajación](07-relaxation.md).
