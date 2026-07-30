# Campaña M1/MnO2 para Yoltla — paquete escalonado V1

Este directorio prepara la campaña M1 sin confundir automatización operativa
con decisiones científicas. Cada `sbatch` mantiene un controlador dentro de la
asignación SLURM y lanza los cálculos SIESTA como pasos `srun --exclusive`.
Los cálculos de una serie se ejecutan secuencialmente, con estado persistente,
pero ninguna serie elige por sí sola el parámetro “ganador”.

## Estado real del paquete

- F1, `M1_U0_FM` de cordura: entrada protegida y materializador listo.
- F3A, serie de malla 200/250/300/350 Ry: definida y separada; requiere la
  aceptación humana F2 del resultado de cordura.
- F3B, serie k 2x2x1/3x3x1/4x4x1: definida; se genera sólo después de firmar la
  malla seleccionada.
- F3C, base; F4, U/espín; F5, relajación; F6, electrónica; F7, complejos:
  conservan su lugar y dependencias, pero permanecen bloqueadas donde el
  protocolo todavía no ha fijado una entrada ejecutable.
- Los PSML de Mn y O son externos por política de distribución. Deben colocarse
  en `external/pseudopotentials/` y coincidir exactamente con los hashes
  auditados.
- La evidencia local sólo confirma `q1h-20p`, 20 CPU y una hora para una prueba
  técnica. No existe evidencia local suficiente para afirmar que una asignación
  de 80 CPU durante 48 horas está disponible. Esa configuración permanece como
  plantilla bloqueada hasta caracterizar Yoltla.

Nada en este paquete llama a `sbatch`. La preparación genera el archivo SLURM;
la presentación sigue siendo una acción humana y sólo pasa el guardián si el
perfil, las compuertas y los hashes están aprobados.

## Flujo

```bash
python3 verify_package.py
python3 scripts/campaignctl.py status

# Después de importar los PSML y de crear la compuerta F0:
python3 scripts/campaignctl.py prepare \
  --phase 01_sanity \
  --profile profiles/yoltla_observed_20c_1h.json

# El archivo se inspecciona y se prueba en Yoltla; no se envía automáticamente.
bash scripts/preflight.sh 01_sanity profiles/yoltla_observed_20c_1h.json
```

La serie F3A se prepara del mismo modo con `--phase 03a_mesh`, únicamente
después de que exista `gates/decisions/F2_SANITY_ACCEPTED.json`.

## Persistencia y aprovechamiento de la asignación

El controlador vive dentro del proceso batch, no en el nodo de login. Una
asignación puede encadenar todos los miembros preautorizados de una serie. Si
se acerca el límite de tiempo, deja de iniciar tareas nuevas, conserva
`state/`, `work/`, `evidence/` y `results/`, y permite reanudar mediante otro
`sbatch` del mismo archivo. No borre esos directorios entre asignaciones.

Las compuertas humanas dividen deliberadamente la campaña en asignaciones:
cordura → auditoría; malla → selección; k-grid → selección; base → selección;
U/espín → selección; relajación → aceptación geométrica. Un ticket largo no
autoriza a saltarse esas revisiones.

## Geometrías encadenadas

Consulte `geometry/GEOMETRY_CHAIN_POLICY.md`. La geometría sólo se promueve si
`STRUCT_OUT` y `XV` concuerdan, las fuerzas cumplen la tolerancia adoptada y se
preservan celda, composición, número atómico, etiquetas y orden. Los FDF
maestros nunca se sobrescriben: las transferencias viven bajo `generated/`.

