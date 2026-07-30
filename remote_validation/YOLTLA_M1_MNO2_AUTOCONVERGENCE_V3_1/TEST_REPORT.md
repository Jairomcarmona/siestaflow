# Informe de pruebas locales

Estado: PASS

## Pruebas ejecutadas

Se ejecutaron 12 pruebas unitarias/de integración:

- Solicitud Slurm exacta 2 nodos, 128 tareas y 64 tareas/nodo.
- Integridad y hashes de Mn.psml y O.psml.
- Contrato estructural del FDF de 54 átomos.
- Materialización Mesh y k-grid con kz=1.
- Base PAO triple-zeta explícita y conservación de semicore Mn 3s/3p.
- DFT+U Dudarev, J=0, método 2 y cutoff automático.
- Partición exacta de los 18 índices Mn para stripe-AFM.
- Selección matemática de meseta y caso sin convergencia.
- Parser de salida SIESTA con SCF, energía, Edftu y evidencia de spin.
- Creación monotónica de carpetas attempt-NNNN.
- Prohibición de comparar energías entre U diferentes.
- Flujo integral Mesh -> k-grid -> base -> U/spin con reutilización trazable.

También se validaron:

- Sintaxis Python.
- Sintaxis Bash de `submit.slurm` e `inspect_campaign.sh`.
- Validación estática del paquete y pseudopotenciales.

## Límites de la prueba

No se ejecutó SIESTA localmente y no se envió ningún trabajo remoto. El
ejecutable y la asignación Slurm se comprueban nuevamente dentro del trabajo
antes del primer cálculo. La ejecución real previa en Yoltla se usó únicamente
como evidencia para adoptar `srun` y el módulo `siesta/5.4.2`.
