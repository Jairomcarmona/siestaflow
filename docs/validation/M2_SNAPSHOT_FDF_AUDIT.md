# Auditoría M2 de FDF del snapshot

## Resultado

`FDF_SNAPSHOT_PARSE_PASS`: se localizaron 17/17 artefactos con sufijo `.fdf`, `.fdf.NO_RUN` o `.fdf.template`. Todos fueron leídos desde el snapshot de solo lectura, preservados byte a byte por el round-trip y procesados sin excepción no clasificada.

| Clase | Cantidad | Parse | Validación estructural |
|---|---:|---|---|
| `REAL_FDF` | 9 | 9 PASS | 9 PASS |
| `NO_RUN_REVIEW_ARTIFACT` | 4 | 4 PASS | 4 FAIL esperados: contienen únicamente comentarios y carecen de bloques ejecutables |
| `TEMPLATE` | 4 | 4 PASS | 4 FAIL esperados: son esqueletos comentados, no inputs completos |

Los ocho FDF de referencias/complejos comparten 31 escalares y cuatro bloques reconocidos. El sanity `M1_U0_FM_PILOT` contiene 26 escalares y cinco bloques, declara 54 átomos, dos especies (`Mn`, `O`), carga, spin, `MD.Steps=0` y tipo de corrida. Su máximo claim es `EXECUTION_READY_PENDING_PREFLIGHT`; no es evidencia de ejecución.

No se observaron includes, redirecciones, etiquetas activas desconocidas, duplicados ni errores de bloques en estos 17 archivos. Estas rutas sí están cubiertas por fixtures de prueba controlados. El inventario completo, hashes, etiquetas, bloques y diagnósticos está en `M2_SNAPSHOT_FDF_AUDIT.json`.

Clasificación de evidencia: resultados y hashes `OBSERVED`; significado científico de los valores `DOCUMENTED_ONLY` y fuera del alcance de M2.
