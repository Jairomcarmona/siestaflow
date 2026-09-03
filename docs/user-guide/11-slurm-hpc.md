# Slurm y HPC

QRAFT no adivina recursos HPC desde el nombre de una cola. Usa las políticas actuales de tu sitio, un perfil aprobado o argumentos explícitos de la CLI. Antes de enviar trabajo, consulta al administrador o la documentación local para partición, cuenta, QoS, nodos, rangos y tiempo.

Ejemplo conceptual (sustituye todos los valores por los aprobados para tu sitio):

```bash
qraft plan campaign.yaml --partition PARTICION --nodes N \
  --np RANGOS --cpus-per-rank CPUS --launcher srun --siesta /ruta/a/siesta
```

Para MPI no uses más rangos de los concedidos por la asignación. El placement usado por launcher debe coincidir con la asignación real. En Slurm, verifica la asignación antes de SIESTA y conserva el output del scheduler junto con el runs-root.

Un perfil puede proporcionar configuración local aprobada. Inspecciona lo disponible con `qraft profile --help`, valida un perfil antes de usarlo y no copies rutas de otro usuario. `squeue` informa carga actual, pero no es autoridad para capacidad ni permisos.
