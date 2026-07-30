# Yoltla M1 MnO2 Autoconvergence V3

Paquete autocontenido para ejecutar exclusivamente pruebas estáticas de
convergencia numérica, base y sensibilidad U/orden magnético del sistema M1
delta-MnO2 neutro de 54 átomos.

## Alcance exacto

El paquete realiza, dentro de una sola asignación Slurm:

1. Mesh.Cutoff: 200, 250, 300 y 350 Ry.
2. Mallas k: 2x2x1, 3x3x1 y 4x4x1.
3. Malla 5x5x1 únicamente si las tres anteriores no alcanzan la tolerancia.
4. Comparación DZP frente a una base triple-zeta polarizada definida mediante
   un bloque PAO.Basis explícito.
5. Control U=0 y las combinaciones Ueff=3.8/4.0 eV por FM/stripe-AFM.

Son 13 pruebas científicas lógicas, 14 como máximo. Se necesitan solamente 12
o 13 nuevas ejecuciones SIESTA porque las referencias DZP y U=0 compatibles se
reutilizan con trazabilidad, sin repetir cálculo.

No ejecuta relajaciones, DOS, PDOS, Bader, complejos con iones ni ninguna fase
de producción.

## Recursos

- Partición: `qz2d-128p`
- Nodos: 2
- Tareas MPI: 128
- Tareas por nodo: 64
- Tiempo: 2 días
- Cada ejecución SIESTA consume las 128 tareas completas.
- No existen calibraciones 20/40/80 ni ejecuciones simultáneas parciales.

## Selección automática

- Tolerancia numérica: 2 meV/átomo.
- Se selecciona el primer nivel cuya diferencia y todas las diferencias
  posteriores disponibles estén dentro de la tolerancia.
- Si 2x2x1/3x3x1/4x4x1 no forman una meseta, se activa 5x5x1.
- DZP se conserva solamente si su diferencia con la base explícita TZP está
  dentro de 2 meV/átomo; de otro modo se selecciona TZP.
- FM y stripe-AFM se comparan únicamente con el mismo U.
- Ueff=3.8 eV es la política primaria del protocolo; 4.0 eV es sensibilidad.
- Las energías de U distintos nunca se usan para elegir U.
- Si el orden magnético cambia entre 3.8 y 4.0 eV o queda degenerado dentro de
  2 meV/Mn, se completan todas las pruebas y el resultado queda marcado
  `COMPLETED_REVIEW_REQUIRED`.

## Trazabilidad

Cada cálculo se registra bajo:

`runs/autoconvergence/calculations/<etapa>/<calculo>/attempts/attempt-NNNN/`

Cada intento contiene el FDF exacto, copias de los pseudopotenciales, hashes,
comando, entorno Slurm, salida, error, resultado analizado y manifiesto de
artefactos. Los intentos nunca se sobrescriben.

Cada etapa produce `summary.csv` y `decision.json`. El nivel global contiene
`events.jsonl`, `traceability.csv` y `final_summary.json`. Las referencias
reutilizadas tienen `reuse.json` con el cálculo fuente y sus hashes.

## Ejecución

Consultar `DEPLOY_TO_YOLTLA.md`. El único envío requerido es:

```bash
sbatch submit.slurm
```

El controlador vive dentro del trabajo Slurm. No requiere daemon, terminal SSH
abierta ni proceso persistente en el nodo de acceso.
