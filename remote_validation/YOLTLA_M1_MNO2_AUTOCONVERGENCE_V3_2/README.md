# Yoltla M1 MnO2 Autoconvergence V3.2

Paquete autocontenido para pruebas estáticas de convergencia numérica, base y
sensibilidad U/orden magnético del sistema M1 delta-MnO2 neutro de 54 átomos.
No ejecuta relajación, DOS, PDOS, Bader ni sistemas con iones.

## Cambios científicos de V3.2

- Cada candidato se compara con todos los niveles superiores probados.
- La aceptación exige simultáneamente energía, fuerza máxima diferencial y
  fuerza RMS diferencial.
- El cierre Mesh-k-base compara la selección con la combinación numérica más
  estricta disponible y promueve automáticamente si falla.
- Un caso DFT+U/magnético representativo verifica la transferencia. Si falla,
  se repite automáticamente toda la matriz U/espín con los parámetros más
  estrictos.
- La tabla Mulliken final se analiza átomo por átomo para los 18 Mn.
- Las energías FM/stripe-AFM no se comparan si las dos inicializaciones
  convergen al mismo patrón o a un patrón no identificable.
- El resultado máximo se denomina
  `ROBUST_WITHIN_TESTED_FM_STRIPE_SET`; no afirma mínimo magnético global.

## Recursos y autonomía

Slurm reserva dos nodos qz, 128 CPU físicas y 48 horas. Dentro de la asignación
se ejecuta un benchmark real 64/128 MPI. El controlador selecciona 128 MPI sólo
si alcanza el speedup mínimo configurado; en caso contrario usa dos cálculos
independientes de 64 MPI en paralelo cuando la dependencia científica lo
permite.

Antes del primer cálculo se valida `srun` en ambos nodos, SIESTA 5.4.2 en ambos
nodos, partición, cuenta, QOS, nodos únicos y CPU físicas. Cada paso utiliza
afinidad `--cpu-bind=cores`.

Los fallos transitorios admiten dos intentos en carpetas inmutables
`attempt-NNNN`. Los fallos determinísticos terminan en modo cerrado. El
controlador consulta el tiempo restante y no inicia una tarea cuando no existe
margen suficiente para terminarla y cerrar con seguridad.

## Trazabilidad

Cada intento conserva FDF, pseudopotenciales, hashes, comando, entorno, salida,
error, fuerzas, momentos Mn, clasificación de warnings y manifiesto. Las
decisiones se guardan como CSV y JSON. Una nueva asignación reutiliza solamente
resultados `PASS` cuyo hash de entrada coincide.

Antes de enviar, siga `DEPLOY_TO_YOLTLA.md`. El estado
`LOCAL_STATIC_PASS_REMOTE_VALIDATION_REQUIRED` significa que el ZIP pasó las
pruebas locales, pero el preflight y el benchmark sólo pueden validarse dentro
de una asignación real de Yoltla.
