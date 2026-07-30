# Contrato M2 de output y artefactos

El parser consume un iterable de líneas y tolera truncamiento. Extrae únicamente evidencia presente: versión, inicio, terminación, SCF, iteraciones, energías reportadas, fuerza máxima, warnings, errores, átomos, especies, spin/magnetización textual, tiempo y nombres de artefactos. Todo resultado lleva `PROVISIONAL_UNTIL_REAL_OUTPUT_IMPORTED`.

Implementa `COMPLETED`, `SCF_NOT_CONVERGED`, `INPUT_ERROR`, `PSEUDOPOTENTIAL_ERROR`, `ENVIRONMENT_ERROR`, `NUMERICAL_FAILURE`, `OUT_OF_MEMORY`, `TIMEOUT`, `NODE_FAILURE`, `CANCELLED`, `TRUNCATED_OUTPUT`, `UNKNOWN_WARNING` y `UNKNOWN_FAILURE`. Una energía sin terminación normal no implica éxito. Warning desconocido o truncamiento exige `REVIEW`; error de pseudo/entorno bloquea; los demás fallos técnicos fallan. Nunca se inventa exit code ni artefacto.

Los nueve fixtures y sus `.expected.json` están marcados `synthetic: true`. No son outputs oficiales ni pueden promovererse a evidencia real.

El catálogo reconoce `.DM`, `.XV`, `.CG`, `.HSX`, `.WFSX`, `.RHO`, `.DRHO`, `.STRUCT_OUT`, `.bands`, `.DOS` y `.PDOS`, y registra ruta, tipo, tamaño, hash, tarea e intento. La política es `automatic_reuse: false` y `default_compatibility: DENY`.
