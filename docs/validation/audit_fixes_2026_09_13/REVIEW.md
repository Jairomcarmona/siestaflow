# Revisión independiente de las correcciones

Base: `9d82c0fdedf3688e4a4257428423a8417fdb52bd`.
Fechas de trabajo: 12–13 de septiembre de 2026.

El usuario autorizó tres subagentes implementadores, coordinación central,
revisión independiente, pruebas locales y commits en una rama aislada. El
coordinador mantuvo la rama original intacta y reunió los cambios en
`codex/audit-fixes`. Este documento registra revisión automatizada; no sustituye
aceptación humana de resultados científicos o de producción HPC.

## Separación de responsabilidades

| Frente | Implementación | Revisión |
|---|---|---|
| H1, cuatro launchers | subagente `fix_launchers` | coordinador y `independent_review` |
| H2/H4/H5, importador | subagente `fix_imports` | coordinador y `independent_review` |
| H3, vistas y recuperación de estado | subagente `fix_views` | coordinador y `independent_review` |
| H6, instalación y CI | coordinador | `independent_review` |

El revisor independiente no editó código ni pruebas del producto. Los agentes
implementadores no crearon commits. Las pruebas y sus resultados se comprobaron
antes de integrar y los commits quedaron bajo control del coordinador.

## Evidencia anterior y posterior al arreglo

- H1: 14 fallos originales; 119 pruebas focalizadas aprobadas tras corregir las
  claves internas. El archivo final incluye 16 casos, dos de ellos con procesos
  Direct reales y acotados. Revisión independiente: 24 aprobadas.
- H2/H4/H5: 31 fallos y 9 controles válidos antes del arreglo; gate focal final:
  56 aprobadas y 1 omitida por contexto histórico. Revisión independiente:
  47 aprobadas con temporales Linux. Un intento en DrvFs no pudo crear FIFO;
  el resultado válido está en `review-imports-linux.xml`.
- H3: 6 fallos originales; 70 pruebas focalizadas aprobadas. La revisión
  independiente encontró un caso adicional: enlaces cíclicos provocaban
  `RuntimeError` en el inventario o en la resolución del journal.
- El subagente H3 añadió siete regresiones para enlaces cíclicos/colgantes y
  comandos con espacios: 6 fallaban y 1 ya pasaba. Después de la corrección,
  el gate ampliado aprobó 77 pruebas. El revisor repitió su reproducción
  original y confirmó que el inventario sigue disponible sin excepción.
- H6: `h6-before.log` reproduce la ausencia de PyYAML. Tras instalar las
  dependencias, `h6-dependencies.log` demuestra que la nueva aserción semántica
  detecta el estado incorrecto de H3; no se consideró suficiente un código 0.

Los logs y XML citados se conservan junto a este documento. Los conteos de
pruebas focalizadas se solapan; no se deben sumar como pruebas independientes.
En los logs versionados se normalizaron espacios finales y terminaciones de
línea; las salidas originales permanecen en `.audit-runtime` del checkout inicial.
`baseline.json` conserva el resumen del diagnóstico original, incluido el E2E
fallido y los resultados de las reproducciones de integridad y cancelación.

## Dictamen del revisor

El revisor emitió `APPROVED_FOR_MERGE` para los seis hallazgos del código final,
condicionado al gate final integrado y al E2E real del coordinador. El hallazgo
adicional de enlaces quedó resuelto y revisado antes de la integración final.
La aprobación del código no implica un merge en la rama original ni una
aceptación de Yoltla.

Se revisaron los contratos de los launchers: se conservan la numeración de
intentos, comandos y retornos públicos de IDs. El importador conserva bundles
válidos, el marcador binario de sha256sum y enlaces internos seguros; rechaza
datos inválidos antes de copiar. Las vistas mantienen la precedencia de las
campañas existentes y exponen múltiples runtimes sin seleccionar uno por el
orden de sus hashes.

El runner `verify_real_e2e.py` y los cambios de CI/documentación se revisaron
sin hallazgos materiales pendientes. El workflow fija las acciones oficiales
a SHAs consultados desde sus repositorios y mantiene permisos de lectura.
Referencias: [checkout](https://github.com/actions/checkout),
[setup-python](https://github.com/actions/setup-python) y
[upload-artifact](https://github.com/actions/upload-artifact).

## Límites preservados

- No se cambian esquemas de persistencia ni formatos de locks.
- El inventario informa presencia; no revalida resultados científicos.
- No se promete protección contra mutación concurrente del bundle durante la
  importación ni se cambia la propagación de señales a hijos MPI remotos.
- CI está configurada para Python 3.11–3.13; su ejecución remota requiere
  publicar los cambios, acción no realizada en esta tarea.
- La validación MPI/SLURM/Hydra de regresión usa procesos controlados; el E2E
  real utiliza SIESTA serial local. No es aceptación de cluster o científica.

El reporte de cierre registrará los resultados finales, commits y hashes del
wheel efectivamente probado.

## Confirmación final de evidencia

El revisor independiente verificó posteriormente el gate de 943 casos
(931 aprobados, 12 omitidos, cero fallos/errores), la ejecución efectiva de la
prueba de instalación limpia y la distribución construida desde el commit
limpio `bde4058e60fd039481523ab2ad860ae0fe59ebbf`.
Contrastó el hash del wheel con el E2E real y sus respuestas de ejecución,
estado, inventario y reanudación. Emitió **APPROVED_FOR_MERGE para aceptación
local**, sin hallazgos bloqueantes pendientes en el alcance revisado.
Los límites científicos, de contexto externo y de CI/HPC remotos permanecen.
