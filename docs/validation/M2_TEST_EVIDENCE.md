# Evidencia de pruebas M2

Fecha: 2026-07-20 (America/Mexico_City).

Comando: `python -m pytest -q`.

Resultado final observado: `113 passed in 3.74s`: 11 pruebas de caracterización M0, 63 pruebas unitarias/integración/smoke M1 y 39 pruebas M2, cero fallos. M2 cubre FDF lossless y malformados; 17 inputs del snapshot; sanity de 54 átomos/dos especies; variantes Mesh/k-grid y rechazo de cambios gobernados; auditoría de pseudos; nueve outputs; sanity y Mesh persistente; stops/resume; SLURM preview; paquete/checksums/preflight; importación; CLI por subprocess; dry-run e integridad 642/642 contra ZIP.

Comandos separados: `tests/characterization` → 11 PASS; `tests/unit tests/integration tests/smoke` → 63 PASS; `tests/m2` → 39 PASS. `compileall` terminó sin error. Toda ejecución fue local y sintética; no se ejecutó SIESTA, MPI, SSH ni SLURM real.
