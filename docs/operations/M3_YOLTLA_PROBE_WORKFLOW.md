# Flujo M3 de caracterización de Yoltla

> **SUPERSEDED:** este documento conserva el contrato histórico M3. El paquete V1 asociado no debe ejecutarse. Para operación utilice exclusivamente `YOLTLA_RUNBOOK.md` y el paquete V2 completo; no mezcle archivos V1/V2.

## Alcance

M3 caracteriza el entorno remoto sin ejecutar cálculos científicos. Codex genera e importa artefactos localmente; la transferencia, el login probe, el envío manual del probe SLURM y la descarga del bundle corresponden al usuario. No existe SSH, SCP, credenciales ni envío remoto automático.

El paquete entregable está en `remote_validation/M3_YOLTLA_ENVIRONMENT_PROBE`. Antes de usarlo, se debe verificar con `python3 verify_local_package.py`. Los comandos completos de copiar y pegar están en `EXACT_COMMANDS.md`; no se debe editar ningún script o YAML.

## Secuencia humana

1. Transferir y extraer el directorio mediante el canal institucional aprobado.
2. Ejecutar el verificador de hashes y `run_login_probe.sh`.
3. Ejecutar `prepare_scheduler_probe.py`. Sólo genera un script si encuentra una asociación cuenta/partición única observada por `sacctmgr`; si hay cero o varias, se bloquea.
4. Inspeccionar `generated/submit_environment_probe.slurm`.
5. Enviar manualmente el trabajo no científico de un nodo/tarea. La plantilla inicial no es ejecutable y termina con código 2.
6. Ejecutar `inspect_probe_job.sh JOB_ID` durante y después. Un `squeue` vacío nunca equivale a éxito; se exige evidencia terminal `sacct` con `State` y `ExitCode`.
7. Ejecutar el colector con `--pseudo-root` apuntando al directorio externo Mn/O. Sólo lee nombres, tamaño, legibilidad, formato y SHA-256; no copia ni modifica pseudos.
8. Descargar manualmente `M3_YOLTLA_ENVIRONMENT_RESULTS_<timestamp>.tar.gz` y adjuntarlo a Codex.
9. Importar localmente con `qraft remote environment import <bundle>`.

## Seguridad y decisión

Los scripts usan `set -euo pipefail`, rechazan sobrescritura y rutas inseguras, limitan outputs, preservan stdout/stderr y filtran nombres sensibles. No usan `sudo`, dotfiles, Conda, instaladores, descargas ni FDF.

El perfil MD/LAMMPS `q1d-20p`/`vini`/20 tareas/`mpiexec.hydra` sólo aparece como `NON_SIESTA_CANDIDATE_PROFILE_DO_NOT_ADOPT`. El perfil canónico permanece con valores `null/MISSING` hasta evidencia real. Sólo un bundle íntegro, no sintético y con todos los criterios puede producir `REMOTE_ENVIRONMENT_ACCEPTED`; en caso contrario queda `REVIEW`, `FAILED` o `INCOMPLETE`.
