# Validar, planear y renderizar

Estos tres pasos no sustituyen a `run`:

```bash
qraft validate campaign.yaml --siesta /ruta/a/siesta
qraft plan campaign.yaml --partition local --launcher openmpi --siesta /ruta/a/siesta
qraft render campaign.yaml --output rendered
```

- **`validate`** comprueba la campaña, el FDF y la evidencia de entrada disponible. Un resultado `BLOCKED` debe corregirse antes de ejecutar.
- **`plan`** muestra DAG, motor, scheduler, launcher, partición, nodos y rangos que QRAFT pretende usar. Es una vista de intención, no una reserva ni un envío a Slurm.
- **`render`** crea un FDF por punto sin ejecutar SIESTA. Revisa `rendered/point_XXX/input.fdf`.

Importante: `plan` puede mostrar una intención aun si un ejecutable dado deja de existir después. `run` repite el preflight y bloquea la campaña antes del engine si SIESTA no está disponible.

Un render exitoso reporta `status: RENDERED`, un manifiesto y la lista de puntos. Guárdalo como evidencia de las entradas que se pretendían ejecutar.
