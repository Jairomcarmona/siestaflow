# Limitaciones M3

- No existe todavía bundle real de Yoltla; el estado vinculante es `REMOTE_EVIDENCE_PENDING`.
- Cuenta, partición, QoS, recursos, módulos, ejecutable/versión SIESTA, MPI, scratch y `sacct` permanecen `null/MISSING` en el perfil canónico.
- La evidencia histórica MD/LAMMPS no se adopta como perfil SIESTA.
- El probe no ejecuta `siesta --version` ni `--help` porque una invocación segura no ha sido demostrada; registra descubrimiento con comando de versión no verificado. Metadatos de módulo pueden aportar versión para revisión.
- El scheduler preparer se bloquea si la evidencia no ofrece exactamente una asociación defendible. No inventa cuenta, partición o QoS.
- Los recursos 1 nodo/1 tarea/1 CPU/2 minutos pertenecen exclusivamente a la política mínima del probe, no a un perfil SIESTA.
- El test de señal confirma trap controlado dentro del job; la política real de señales del scheduler aún requiere evidencia remota.
- El colector no encuentra automáticamente scratch si la evidencia no lo declara; el campo permanece nulo.
- Los pseudos nunca se empaquetan. Su disponibilidad y hash sólo pueden verificarse en la ruta que indique el usuario en Yoltla.
- Un job `COMPLETED` no basta por sí solo para aceptación; también se exigen SIESTA, MPI, filesystem, pseudos y ausencia de contradicciones.
- M4 está fuera de alcance y no puede iniciarse antes de una decisión M3 basada en evidencia real.
