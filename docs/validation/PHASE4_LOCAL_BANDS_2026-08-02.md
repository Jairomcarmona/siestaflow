# Bandas locales reproducibles — Fase 4

Fecha: 2026-08-02  
Estado: `LOCAL_BAND_STRUCTURE_AND_EXPORT_VALIDATED`

## Alcance

La receta `siestaflow.recipe.siesta.band-structure` y el consumidor
`results bands` fueron validados por la ruta canónica:

```text
intent con BandLines explícito
→ workflow.lock.json
→ run prepare
→ run.lock.json
→ paquete autocontenido
→ Slurm local
→ .bands
→ bands.csv + manifiesto hash-bound
```

El FDF contiene una trayectoria técnica explícita `Gamma → X`. SIESTAFLOW no
la generó ni escogió simetría, dimensionalidad, k-grid, referencia energética o
criterio de gap.

## Ejecución

Fuente limpia: `f0dbee2fd969b34389e05a7addf081bc9ddadbbf`.

| Elemento | Resultado |
|---|---|
| preflight | `PASS`, sin hallazgos |
| `python verify_package.py` | PASS |
| `bash -n submit.slurm` | PASS |
| `sbatch --test-only submit.slurm` | PASS |
| job Slurm local | `48`, `COMPLETED`, 1/1 tarea |
| artefacto | `phase4_bands.bands` |
| exportación | 5 puntos k, 26 bandas, 1 espín, 130 filas |
| interpretación científica | `NOT_PERFORMED` |

## Procedencia e integridad

| Elemento | SHA-256 |
|---|---|
| workflow lock | `c7bce4b665fd52a92c42dc51d245ed45ca5c96081b526080f2f2cc842b5c8361` |
| run lock | `3b9a90dcb1b5d8f5cc56959ba51ed888d3af9abfa6e84980a39493d7b2dfc161` |
| `.bands` | `027a820735dd0a7bcc026cc3e4c6440ba8e103719361d7e2e4430bfc03bf9b88` |
| `bands.csv` | `5ebdbe7c8eb61f3cd85aea4d15438f117285f5c5adc25d885a2432a8eb516137` |
| manifiesto de exportación | `feeabda933f0a0a988beb27b62637bc7102bce3cc24b689be5ff7e1be044c12c` |
| ZIP autocontenido | `bd7fa4b0f9a3901e01a44f7b129350dab0f4aa6decface2519640676c274d92f` |

El manifiesto conserva la energía de Fermi y rangos exactamente como SIESTA los
escribió. No se desplazaron bandas ni se declaró banda prohibida, carácter
metálico, dispersión, simetría, o propiedad científica alguna. El fixture de Si
de dos átomos es exclusivamente evidencia técnica local.
