# Changelog V2

- Nueva identidad `YOLTLA_M1_MNO2_STAGED_CAMPAIGN_V2`.
- PSML auditados de Mn y O incluidos en el ZIP por instrucción del usuario.
- Perfil qz2d-128p específico y perfiles derivados bajo `site/profiles/`.
- Solicitud 2 nodos × 40 tareas, 80 totales, 2 días; memoria de partición.
- Walltime Slurm con forma de días y validación estricta.
- Módulos estructurados y versión SIESTA 5.4.2 obligatoria.
- Launchers Hydra SSH y srun desacoplados; bootstrap Slurm prohibido para Hydra.
- Administrador de slots por nodo y layouts 1×80, 2×40, 4×20.
- Preflight de login y preflight MPI dentro de la asignación.
- Reintentos transitorios, fallos terminales, persistencia y reanudación.
- Bundles de calibración, sanity+malla y k-grid.
- Gate técnica automática para sanity sin apropiarse de decisiones científicas.
- F0 sin aceptación prefabricada.
- Materialización FDF determinista y procedencia única.
- Guardas SHA-256 para perfil, gates, FDF y pseudopotenciales.
- Captura ampliada de evidencia remota.
- Suite V2 ampliada; no se añadió envío automático.
