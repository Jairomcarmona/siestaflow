# Changelog V3.2

- Corrige la falsa meseta por deltas adyacentes.
- Añade convergencia simultánea de energía y fuerzas.
- Añade cierre Mesh-k-base y transferencia representativa DFT+U.
- Analiza momentos Mulliken finales de los 18 Mn y guarda CSV por intento.
- Renombra el estado máximo a `ROBUST_WITHIN_TESTED_FM_STRIPE_SET`.
- Separa 128 CPU asignadas de 64/128 rangos MPI por paso.
- Añade benchmark automático 64/128 y concurrencia 2x64.
- Añade preflight real en ambos nodos y afinidad a núcleos físicos.
- Añade reintentos de fallos transitorios, clasificación de warnings y guardia
  preventiva de walltime.
- Mantiene sin cambios la convención Dudarev, proyectores, Ueff y
  pseudopotenciales.
- El estado del paquete es `LOCAL_STATIC_PASS_REMOTE_VALIDATION_REQUIRED`.
