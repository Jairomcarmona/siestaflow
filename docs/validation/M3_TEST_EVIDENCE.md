# Evidencia de pruebas M3

Fecha: 2026-07-20 (America/Mexico_City).

La regresión final produjo `128 passed in 4.75s`: 11 pruebas de caracterización M0, 63 pruebas M1, 39 pruebas M2 y 15 pruebas M3. Las pruebas M3 cubren reproducibilidad, estructura, ausencia de archivos científicos/secretos, dry-run, guardas shell, no envío automático, comandos humanos, redacción sensible, importación sintética, alteración, incompletitud, `squeue`, pseudos, traversal, hashes auditados, perfil nulo, CLI y prohibición del claim científico.

Resultados separados: M0 `11 PASS`; M1 `63 PASS`; M2 `39 PASS`; M3 `15 PASS`. `compileall` terminó sin error. El paquete materializado pasó su verificador interno y todos sus scripts Python compilaron.

No se ejecutó SIESTA, ningún FDF, sanity, Mesh, MPI científico, SSH ni SLURM real. No se invocó `sbatch` localmente.
