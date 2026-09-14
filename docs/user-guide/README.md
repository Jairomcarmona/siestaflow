# Guía de usuario de QRAFT

QRAFT prepara y ejecuta campañas SIESTA reproducibles: explora una serie de valores, decide si la métrica convergió y puede continuar con una relajación de celda fija. Esta guía usa sólo comandos públicos y archivos que puedes abrir.

1. [Instalación](01-installation.md)
2. [Inicio rápido](02-quickstart.md)
3. [El archivo `campaign.yaml`](03-campaign-yaml.md)
4. [Validar, planear y renderizar](04-validation-planning-rendering.md)
5. [Ejecutar campañas](05-running-campaigns.md)
6. [Convergencia](06-convergence.md)
7. [Relajación](07-relaxation.md)
8. [Estado, resultados y `qraft.out`](08-status-results-qraft-out.md)
9. [Interrupción y reanudación](09-interruption-resume.md)
10. [Archivos y trazabilidad](10-files-provenance.md)
11. [Slurm y HPC](11-slurm-hpc.md)
12. [Solución de problemas](12-troubleshooting.md)
13. [Referencia de CLI](13-cli-reference.md)

## Antes de empezar

Necesitas un FDF de SIESTA y los pseudopotenciales que ese FDF referencia. QRAFT instala su CLI y dependencias Python; no instala SIESTA, MPI ni Slurm. Los comandos siguientes se ejecutan desde el directorio de tu proyecto.

## Tres recetas

- **A — sólo convergencia:** sigue [Inicio rápido](02-quickstart.md).
- **B — convergencia y relajación:** sigue [Relajación](07-relaxation.md).
- **C — interrupción y recuperación:** sigue [Interrupción y reanudación](09-interruption-resume.md).
