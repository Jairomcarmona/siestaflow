# Demostración local M3

Fecha: 2026-07-20. Se ejecutó en un directorio temporal, sin red ni procesos científicos.

1. El generador produjo 17 archivos deterministas del paquete M3.
2. `verify_local_package.py` devolvió `M3_PACKAGE_HASHES_VERIFIED`.
3. Todos los scripts Python empaquetados compilaron.
4. No se encontraron FDF, geometrías, PSML/PSF ni comandos ejecutables de envío. La única línea `sbatch` está en la documentación para ejecución humana.
5. Se creó un bundle explícitamente sintético con todos los requisitos técnicos satisfechos.
6. El importador verificó identidad, manifest, hashes, archivos y criterios.
7. La decisión fue `REMOTE_ENVIRONMENT_REVIEW`, nunca aceptación, por `SYNTHETIC_BUNDLE_REJECTED_AS_REAL_EVIDENCE`.
8. El perfil candidato marcó sus valores como `INFERRED`; el perfil canónico no se promovió.

Resultado observado:

```text
PACKAGE_FILES 17
PACKAGE_STATUS REMOTE_EVIDENCE_PENDING
IMPORT_STATUS REMOTE_ENVIRONMENT_REVIEW
SYNTHETIC True
ALL_TECHNICAL_REQUIREMENTS True
PROFILE_PARTITION_STATUS INFERRED
CANONICAL_PROFILE_PROMOTED False
```

Fixtures adicionales demostraron bundle alterado → `FAILED`, incompleto → `INCOMPLETE`, `squeue` vacío sin terminal → `REVIEW`, pseudo incorrecto → `FAILED` y tar con traversal → rechazo sin extracción.
