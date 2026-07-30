# Checklist remoto

Marque cada punto con evidencia actual; una marca local no sustituye la prueba
en Yoltla.

- [ ] `python3 verify_package.py` pasa después de descomprimir.
- [ ] Hashes de Mn.psml y O.psml coinciden.
- [ ] `capture_site_evidence.sh` terminó y cada comando obligatorio tiene
      `capture_exit_code=0`.
- [ ] qz2d-128p está UP y conserva 2 nodos, ncz/zen3/mem512,
      `ExclusiveUser=YES`, sin DRAIN/MAINT/reserva conflictiva.
- [ ] Account `vini` y QoS `normal` son válidos para el usuario.
- [ ] La omisión de `--mem` es compatible con la política vigente.
- [ ] `module load siesta/5.4.2` activa exactamente SIESTA 5.4.2.
- [ ] `mpiexec.hydra` existe, su ayuda fue capturada y usa bootstrap SSH.
- [ ] El perfil se construyó bajo `site/profiles/` y se aprobó explícitamente.
- [ ] El layout seleccionado tiene responsable y razón; no se presenta como
      eficiencia demostrada si solo es provisional.
- [ ] F0 liga perfil, FDF, PSML, backend, preflight, salida y alcance.
- [ ] Las demás gates del bundle están aceptadas y sus hashes pasan.
- [ ] `campaignctl prepare` se ejecutó después de las aprobaciones definitivas.
- [ ] `launch_guard.json` conserva el hash vigente del perfil y gates.
- [ ] `preflight.sh` pasa y `sbatch --test-only` acepta el script exacto.
- [ ] El envío real se hará manualmente.
- [ ] Dentro del ticket, `runtime_preflight.json` demuestra ambos nodos, versión
      MPI, host subset, topología y accesibilidad de entradas.
- [ ] No se borrarán `state/`, `work/`, `evidence/` ni `results/`.
- [ ] Una reanudación solo se enviará cuando el trabajo anterior sea terminal.

Si falla cualquier punto anterior: `BLOCKED_BY_REMOTE_EVIDENCE`.
