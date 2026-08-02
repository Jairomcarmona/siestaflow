# Óptica local reproducible — Fase 4

Estado: `LOCAL_OPTICAL_SPECTRUM_AND_EXPORT_VALIDATED`

La receta `siestaflow.recipe.siesta.optical-spectrum` se ejecutó localmente por
la ruta canónica. Exigió `OpticalCalculation T`, rango en eV, broadening,
número de bandas, malla y polarización explícitos. No eligió ninguno de esos
parámetros.

| Comprobación | Resultado |
|---|---|
| preflight | PASS |
| verificador de paquete | PASS |
| sintaxis Bash | PASS |
| Slurm local | job `50`, `COMPLETED`, 1/1 |
| salida SIESTA | `phase4_optics.EPSIMG` |
| exportación | 251 filas, `epsimg.csv` |
| interpretación | `NOT_PERFORMED` |

| Elemento | SHA-256 |
|---|---|
| workflow lock | `80bed70c872f8f64647651f8d2bb0e2c30c4368b38a89d8aea736f8f535c6da0` |
| run lock | `9d2c131453e371779e2354f69e53afa13f5aecf4e0b677d4f851667fd8ded7bf` |
| EPSIMG | `ccd4890dc343fb90a865ac2e06440326b871ae6cdabdcee0bbed35f58df42ad4` |
| tabla | `76045781071b5c3bd99d80138b25a5aaf5a08ad3207871283c83032b6f31efad` |
| manifiesto | `dd00f47309116eca22f9916d00f016e0da2736b3bf01d3076f5220eeec857c4f` |

Esta es evidencia técnica local con un fixture de Si de dos átomos. No prueba
una respuesta óptica científicamente convergida ni permite concluir absorción,
gap o picos.
