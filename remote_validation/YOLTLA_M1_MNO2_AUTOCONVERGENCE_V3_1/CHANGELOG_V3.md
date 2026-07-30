# Cambios respecto de V2

- V3.1 carga explícitamente `python/3.12` después de `module purge`, evitando
  que Yoltla use su Python de sistema antiguo.

- Se reemplazó 2x40/80 MPI por la solicitud obligatoria 2x64/128 MPI.
- Se eliminaron calibraciones 20/40/80 y layouts parciales.
- Se eliminó toda fase de relajación, electrónica y complejos.
- Se añadieron selección automática Mesh y k-grid, incluido 5x5x1 condicional.
- Se añadió comparación DZP frente a PAO.Basis triple-zeta explícita.
- Se cerró DFT+U con Dudarev, J=0, método de proyectores 2 y cutoff automático.
- Se añadieron Ueff=3.8/4.0 por FM/stripe-AFM.
- Se prohibió seleccionar U comparando energías entre U distintos.
- Se añadieron carpetas inmutables por intento, hashes, linaje, resúmenes CSV y
  decisiones JSON.
- Se adoptó `srun`, validado por el cálculo real anterior en Yoltla.
- Se incorporaron Mn.psml y O.psml con hashes fijados.
