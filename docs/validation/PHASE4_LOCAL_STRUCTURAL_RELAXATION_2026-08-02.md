# Fase 4 — relajación estructural local con SIESTA real (2026-08-02)

## Alcance

Esta es una prueba técnica local mínima de la primera capacidad de relajación.
No es una campaña científica, no usa un sistema de referencia del proyecto y
no sustituye una aceptación HPC. El sistema es una celda técnica de Si de dos
átomos, con un solo paso CG y sin interpretación de energía o estructura.

## Ruta canónica y procedencia

```text
ScientificIntent
-> WorkflowDefinition
-> workflow.lock.json
-> run prepare
-> run.lock.json
-> paquete autocontenido
-> sbatch local -> srun -> SIESTA
```

| Campo | Valor |
|---|---|
| Commit fuente | `d0cef057d4080b422054d6e3ac466163b3d186e7` (árbol limpio) |
| Job Slurm local | `18`, `COMPLETED`, `ExitCode=0:0` |
| Partición/nodo | `local` / `LAPTOP-NFD67ATK` |
| Workflow lock SHA-256 | `a96e4f23d9a1d200701f5f337264e90cdd2b2f7869d4acee56ffdd9b08b8a3d4` |
| Run lock SHA-256 | `56d12516592c44a70d6346793d8de0aaebd0a152088b3cdcb5ca346f6ff3ae1a` |
| Paquete SHA-256 | `a29215bcb5dd4fc4ce6823b2e4e4f4089230a398cc6471df0b051cdd3a1b5ba7` |
| Archivo PSML de Si SHA-256 | `6a6bf03d3996eb7c2304df0305ba5a7856477331c19e6de2eab0153412cb0821` |
| Archivo `.XV` SHA-256 | `3ff3dfd38d4eed3f99b977292c357ad3911595ca989675a5d2167e0a379ed724` |
| Archivo fuente de pseudopotenciales SHA-256 | `6745992e28d9bf7e90bf36e3cbd7c1cbf49efea4b402ed2d2d7a79a954cf0539` |

El `workflow preflight` final devolvió `PASS`; `verify_package.py`, `bash -n
submit.slurm` y `sbatch --test-only submit.slurm` también pasaron antes del
envío local.

## Evidencia observada

- `relax_structure` completó en un intento.
- SIESTA registró dos ciclos SCF convergidos y `Job completed`.
- El controlador verificó código de salida, terminación normal, hashes de FDF
  y PSML, y el artefacto requerido `si_relax_technical.XV`.
- La única advertencia del parser fue la deprecación de
  `BASIS_ENTHALPY`/`BASIS_HARRIS_ENTHALPY`; no bloqueó la ejecución.

## Correcciones descubiertas durante la prueba

1. `cc36f22` reconoce unidades físicas compuestas como `eV/Ang` y no confunde
   texto descriptivo con una unidad.
2. `75744a0` exporta el entorno del perfil antes de comprobar el ejecutable
   SIESTA en `submit.slurm`.
3. `d0cef05` reconoce `MD.NumCGSteps` como límite válido de una relajación CG.

## Límites

Esta evidencia sólo valida el recorrido técnico local para una relajación CG
de juguete. No aprueba parámetros numéricos, no valida propiedades de Si, no
habilita propagación automática a análisis posteriores y no constituye prueba
remota en Yoltla.
