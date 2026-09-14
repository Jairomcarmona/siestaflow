# DOS/PDOS local — Fase 4

Fecha: 2026-08-02
Estado: `LOCAL_TECHNICAL_DOS_PDOS_VALIDATED`

## Dictamen

El primer consumidor electrónico modular se ejecutó por la ruta canónica con
SIESTA local:

```text
ScientificIntent DOS/PDOS
→ WorkflowDefinition
→ workflow.lock.json
→ run prepare
→ run.lock.json
→ paquete autocontenido
→ Slurm local
→ SIESTA
→ DOS y PDOS hash-verified
```

El job local `42` terminó `COMPLETED`, y la tarea `dos_pdos` produjo tanto
`phase4_dos_pdos.DOS` como `phase4_dos_pdos.PDOS`. El manifiesto de resultado
verificó ambos junto con la terminación y las entradas.

## Alcance y límites

- Fixture técnico local: celda de Si de dos átomos y PSML proporcionado por el
  usuario.
- Ventana PDOS `EF -15 15 eV`, anchura `1 eV` y 61 puntos: valores de bajo
  coste para integración, **no** parámetros científicos aprobados.
- La salida informó cálculo Gamma y posible interacción entre imágenes
  periódicas. No se interpretaron picos, brechas, ocupaciones ni propiedades.
- No hubo ejecución ni afirmación sobre Yoltla.
- El paquete fallido anterior (`SinglePoint`) se preserva como diagnóstico;
  no se reutilizó. La corrección exige el modo SIESTA válido `CG` con
  `MD.NumCGSteps 0`.

## Procedencia

Fuente limpia: `1cdf927183409733617c29123eb839eb2d16bb8f`.

| Elemento | SHA-256 |
|---|---|
| contenido de `workflow.lock.json` | `60f90069c2a6c909bf2577757f5b4dfd43479431528bdd110379013aa64f3faf` |
| envelope de `workflow.lock.json` | `4642510c8be2702e1eecb27a1f8166f95330cbfeb3becac8928a9439db4bab02` |
| contenido de `run.lock.json` | `64ef8089aa559bf8379b49e4a8deb1dbcc0c0e9afecca91e6b79096fd2686c6b` |
| envelope de `run.lock.json` | `d9d161ea1dcecdf4f637328efd5b14eca55ec31bee1a47dce23154620a969730` |
| artefacto DOS | `cdf16e305837bfb90bc500465932774e2c53b5455e8b5805abfa49538a592651` |
| artefacto PDOS | `4a8bcbf8224fd14c5b0520a3579eba16a0d844a54ec173c7c1e1e158d77af3aa` |
| ZIP autocontenido | `d57dd303b4c9b0cd8e57738970bec9693580195de6a9adc60bb9a675b38f16f8` |

El DOS contiene 61 puntos, como exige el FDF técnico; el PDOS contiene 2044
líneas. Estas cantidades corroboran la producción de ficheros, no su validez
científica.

## Verificaciones

```text
workflow preflight                    PASS, sin hallazgos
python verify_package.py              PASS
bash -n submit.slurm                  PASS
bash -n progress.sh                   PASS
python -m zipfile -t ZIP              PASS
sbatch --test-only submit.slurm       PASS
job 42                                COMPLETED, 1/1 tarea
SIESTA stdout                         Job completed; sección pdos presente
```

## Conclusión

DOS/PDOS ya es una receta CLI modular y aislable que reutiliza el motor SIESTA,
el compilador, `run prepare` y el controlador existentes. El siguiente corte no
debe añadir interpretación automática: debe definir un consumidor de resultados
(tabla/serie/exportación) o el contrato de continuación desde un estado
electrónico, antes de implementar bandas u óptica.
