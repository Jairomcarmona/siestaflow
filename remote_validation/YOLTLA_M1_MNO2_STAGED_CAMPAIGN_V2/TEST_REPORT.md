# Reporte de pruebas

## Alcance local

- Suite V2: pruebas de perfil, walltime, versión, launchers, hostfile,
  topologías, reintentos, fallo terminal, walltime, persistencia,
  materialización, tamper de perfil/gate/PSML, bundle y ausencia de envío.
- Verificación de sintaxis Python y Bash.
- Integridad científica del FDF base, geometrías y PSML.
- Verificador de cobertura inmutable y ZIP reproducible.

## Resultado

- Suite V2: **18 pruebas superadas**, 0 fallos.
- Suite completa SIESTAFLOW: **263 pruebas superadas**, 0 fallos.
- `verify_package.py`: integridad, cobertura inmutable, sintaxis y contratos
  científicos superados.
- Hashes definitivos: registrados en `manifest.json`, `checksums.sha256` y en
  el archivo `.zip.sha256`.

Las pruebas de Slurm/MPI locales usan mocks y **no demuestran compatibilidad
remota**.

## Limitaciones obligatorias

- No se ejecutó SIESTA en Yoltla desde este entorno.
- No se midió escalamiento 20/40/80 real.
- No se probó binding físico concurrente en nodos ncz.
- No se declara disponibilidad permanente de qz2d-128p.
- F0 y decisiones científicas no vienen aceptadas.

Dictamen local: `PASS`.

Dictamen launcher/Yoltla: `BLOCKED_BY_REMOTE_EVIDENCE`.

Dictamen fases posteriores a convergencia numérica:
`BLOCKED_BY_SCIENTIFIC_DECISION`.
