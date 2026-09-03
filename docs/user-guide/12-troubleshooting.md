# Solución de problemas

| Síntoma | Significado | Qué revisar | Qué no hacer |
|---|---|---|---|
| `QRAFT_ERROR` al leer YAML | YAML incompleto o mal formado | Indentación, listas y campos del template | No borres el runs-root existente. |
| `FDF_MISSING` | No se encontró el FDF | `system.fdf`, directorio actual, permisos | No inventes un FDF vacío. |
| Bloques FDF faltantes | El FDF no es entrada SIESTA suficiente | `qraft validate`, species, lattice y coordenadas | No ignores `BLOCKED`. |
| `SCIENTIFIC_INPUT_INCOMPLETE` | Falta pseudo o evidencia científica | Manifiesto y archivos pseudo | No ejecute con pseudos de otro sistema. |
| Launcher inválido | La CLI no reconoce el launcher | Usa `direct`, `hydra`, `openmpi` o `srun` | No escribas un nombre arbitrario. |
| Engine `BLOCKED` | SIESTA no es ejecutable o accesible | `--siesta`, permisos, `qraft env` | No asumas que `plan` garantiza disponibilidad en run. |
| `SCIENTIFIC_NOT_CONVERGED` | La campaña técnica terminó sin criterio científico | Métrica, delta, puntos y criterio | No declares una selección manual. |
| `INTERRUPTED` | La campaña puede reanudarse | `status`, `qraft.out`, luego `resume` | No borres attempts. |
| `FAILED` en relaxation | Downstream no produjo evidencia suficiente | `downstream/.../stderr.txt`, FDF y `STRUCT_OUT` | No copies la geometría inicial como final. |
| Artefacto faltante | No hay prueba suficiente del resultado | `attempt.json`, stdout/stderr y outputs SIESTA | No marque PASS manualmente. |

Si necesitas soporte, comparte `qraft.out`, `qraft status --json`, el comando público usado y los `stdout.txt`/`stderr.txt` del attempt afectado; no reemplaces esos archivos.
