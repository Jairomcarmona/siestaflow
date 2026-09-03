# Referencia de CLI

Usa `qraft COMANDO --help` para la autoridad de la versión instalada.

| Comando | Propósito | Ejemplo | Resultado/exit |
|---|---|---|---|
| `qraft` | Abre la interfaz interactiva. | `qraft` | Muestra bienvenida y prompt. |
| `qraft init [PATH]` | Crea un template editable. | `qraft init campaign.yaml` | Rechaza sobrescribir salvo `--force`. |
| `qraft validate FDF` | Valida campaña/FDF y preflight. | `qraft validate campaign.yaml --siesta /ruta/a/siesta` | `BLOCKED` impide ejecución. |
| `qraft plan FDF` | Muestra intención de ejecución. | `qraft plan campaign.yaml --partition local --launcher openmpi` | No reserva ni ejecuta. |
| `qraft render FDF` | Materializa variantes sin engine. | `qraft render campaign.yaml --output rendered` | Produce manifiesto y FDF. |
| `qraft run FDF` | Ejecuta y persiste campaña. | `qraft run campaign.yaml --runs-root .qraft-runs ...` | Preflight bloquea condiciones no ejecutables. |
| `qraft status` | Muestra estado de runs-root. | `qraft status --runs-root .qraft-runs` | `--json` ofrece salida estructurada. |
| `qraft resume FDF` | Reanuda campaña guardada. | `qraft resume campaign.yaml --runs-root .qraft-runs ...` | Reutiliza evidencia válida. |

Argumentos recurrentes de `plan`, `run` y `resume`: `--partition`, `--nodes`, `--np`, `--cpus-per-rank`, `--launcher`, `--siesta`, `--profile`, `--runs-root` y `--json` cuando esté disponible. Los launchers admitidos por la CLI actual son `direct`, `hydra`, `openmpi` y `srun`.

Un error de argumentos tiene exit no cero y texto de uso. Un preflight bloqueado impide el engine y deja diagnóstico legible. Revisa `--help` de la instalación usada, porque los argumentos disponibles pertenecen a esa versión del wheel.
