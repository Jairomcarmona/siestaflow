# Cierre de correcciones de auditoría QRAFT

Fecha: 13 de septiembre de 2026.

**Resultado: los seis hallazgos quedaron corregidos y validados localmente.**
El revisor independiente emitió **APPROVED_FOR_MERGE para aceptación local**.
No se hizo merge en la rama original, push, publicación ni creación de tags.

## Validación final

| Control | Resultado |
|---|---|
| Suite completa, incluyendo instalación limpia | **931 PASS, 12 SKIPPED, 0 FAIL/ERROR**; 943 casos, 199.68 s |
| Regresiones nuevas | 80 casos añadidos frente a los 863 del corte auditado |
| Compilación de `src` y `pip check` | **PASS** |
| Inspección del diff y control previo a commits | **PASS** |
| Revisión independiente del código y evidencia final | **APPROVED_FOR_MERGE**, alcance local |
| Wheel y sdist desde commit limpio | **PASS** |
| Comparación wheel/fuentes | **143 archivos Python idénticos**, datos del motor presentes, sin archivos inesperados |
| E2E con SIESTA 5.4.2 serial real | **PASS**, cinco condiciones semánticas satisfechas |
| Ejecución remota de CI | **No ejecutada**; workflow versionado |

La prueba de instalación limpia se ejecutó; no está entre las omisiones.
Los 12 casos omitidos requieren `QRAFT_HISTORICAL_CONTEXT_ROOT`. La política
existente también excluye de colección caracterización QEF y procedencia M3B1
sin sus inputs externos. No se convirtieron esas exclusiones en éxitos.

Evidencia: [resumen de pruebas](final-tests.json), [JUnit completo](final-suite.xml),
[log](final-suite.log), [revisión independiente](REVIEW.md) y
[metadatos de distribución](distribution.json).

## Qué cambió

| Hallazgo | Corrección | Protección contra regresiones |
|---|---|---|
| H1: cancelación pierde procesos con igual número de intento | Los cuatro launchers indexan procesos por tarea e intento | Cancelación y finalización concurrentes, terminate/kill y procesos Direct reales |
| H2: checksums vacíos aceptan resultados alterados | Cobertura obligatoria de todos los payloads requeridos, formato de hash y unicidad | Casos vacíos, incompletos, duplicados, alterados y controles válidos |
| H3: cálculo terminado aparece NOT_STARTED | Estado e inventario derivados de los runtimes canónicos, manteniendo compatibilidad | Runtime real con motor sintético, múltiples runtimes, corrupción, lectura sin escrituras y E2E instalado |
| H4: importación lee rutas exteriores | Validación de rutas y del árbol, incluidos enlaces no listados, antes de leer/copiar | Traversal, rutas absolutas, enlaces exteriores, ciclos y archivos especiales |
| H5: manifiesto JSON inválido provoca excepción | Validación de objeto, identidad y tipos de indicadores | Entradas incorrectas producen REMOTE_RESULTS_INVALID sin crear importación |
| H6: instalación de prueba omite PyYAML | Wheelhouse con dependencias declaradas e instalación aislada sin índice | CLI instalada, pip check, ubicación del módulo, estado/resultados y recuperación inmutable |

Durante la revisión independiente apareció otro caso en H3: enlaces cíclicos
en intentos, runtimes o journal podían hacer fallar las vistas. Se corrigió y
se añadieron regresiones antes del gate final. Los comandos sugeridos también
preservan rutas con espacios.

Se conservan esquemas de evidencia, formatos de locks, numeración de intentos,
comandos MPI y retornos públicos de IDs de los launchers. No se introdujeron
refactorizaciones de arquitectura ni cambios de parámetros científicos.

## End to end con el paquete instalado

Se utilizó un entorno virtual nuevo fuera del checkout, sin `PYTHONPATH` ni
paquetes del usuario. El wheel se instaló con sus dependencias y se comprobó
que el módulo importado perteneciera a ese entorno.

Se copiaron el FDF y los pseudopotenciales del pequeño fixture MgO existente,
se seleccionó explícitamente el SIESTA serial local y se ejecutó desde una
ruta con espacios. Se verificaron instalación, dependencias, importación,
versión, ayuda, creación de plantilla, entorno, check, plan, ejecución,
estado, inventario y reanudación: **13 comandos, todos con salida 0**.

Las cinco comprobaciones finales fueron:

1. El cálculo terminó con validación técnica PASS.
2. `status` informó COMPLETED, con progreso 1/1.
3. `results` incluyó el manifiesto y stdout existentes del intento.
4. `resume` devolvió REUSED_VALIDATED_ATTEMPT.
5. Permaneció un único manifiesto de intento con el mismo hash.

La prueba de `init` es un paso separado; el cálculo usa el fixture MgO, no una
plantilla sin completar. El preflight conserva advertencias de revisión del
input. La aceptación es de ejecución y evidencia, no de precisión física,
convergencia de parámetros ni aprobación científica.

Evidencia: [resumen E2E](real-e2e-summary.json), [run](real-run.json),
[status](real-status.json), [results](real-results.json),
[resume](real-resume.json), [check](real-check.json) y [entorno](real-env.json).
El runner reproducible está en [verify_real_e2e.py](verify_real_e2e.py).
La copia completa del runtime y los logs originales permanece en
`C:/Users/Jairo/Downloads/QRAFT/.audit-runtime/final-e2e/`; las rutas `/tmp`
registradas describen la ejecución original y pueden ser efímeras.

## Control de versión y procedencia

Base auditada: `9d82c0fdedf3688e4a4257428423a8417fdb52bd`.
Rama de correcciones: **`codex/audit-fixes`**.

| Commit | Alcance |
|---|---|
| `746467d` | Seguimiento y cancelación de tareas |
| `1a46cdb` | Integridad, rutas y manifiestos de importación |
| `46138b2` | Estado e inventario canónicos |
| `3bcbcbf` | Instalación limpia y controles Linux CI |
| `bde4058` | Changelog, documentación y evidencia de regresión revisada |

El paquete probado fue construido desde
**`bde4058e60fd039481523ab2ad860ae0fe59ebbf`**, con `source_tree_dirty=false`.
El commit que incorpora este reporte añade únicamente evidencia de cierre;
no cambia el código del paquete probado.

- Wheel SHA-256: `28d4d50011710dbc313a5221bd5a41ffe158f43c5056c669734539e0031e4996`.
- Sdist SHA-256: `99a84ac65c68987c7a9c99e4c453dd53fc53289ea956ab5b9c6c5123d979b378`.

La distribución conserva la versión 0.2.0: estos son cambios unreleased y no
constituyen una publicación. Los artefactos están en
`C:/Users/Jairo/Downloads/QRAFT/.audit-runtime/release-dist/`.

La rama original `feat/qraft-m10-hpc-production-acceptance` permanece en su
commit inicial. Los worktrees de los subagentes se conservaron para revisión;
la integración versionada está en
`C:/Users/Jairo/Downloads/QRAFT/.audit-worktrees/integration/`.

## Controles que quedan instalados

- Regresiones por fallo y controles de comportamiento válido.
- Gate de distribución con dependencia completa, ejecución desde instalación
  aislada y verificaciones semánticas de recuperación.
- Workflow Linux para Python 3.11, 3.12 y 3.13, con acciones fijadas a SHAs y
  permisos de lectura. La validación local de esta tarea usó Python 3.12.3,
  pytest 9.1.1 y PyYAML 6.0.3.
- Documentación de criterios de aceptación, límites y resolución de errores.

El workflow todavía no se ejecutó en GitHub y no se configuraron reglas
remotas de protección de ramas. Tampoco se ejecutaron jobs Yoltla ni pruebas
MPI multinodo. Esas validaciones requieren sus entornos y evidencia propios.

El revisor independiente contrastó el JUnit final, el origen limpio del
paquete, la igualdad del hash del wheel y las respuestas reales del E2E. No
quedan hallazgos bloqueantes dentro del alcance local autorizado.
