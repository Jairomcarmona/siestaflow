# Limitaciones M1

## Deliberadas

- No existe parser/generador/launcher/output parser SIESTA ni lógica FDF.
- No existen `SrunLauncher`, `MpiexecHydraLauncher` ni `MpirunLauncher`.
- No existe cliente SLURM real ni llamadas a `sbatch`, `squeue`, `sacct`, `scontrol` o `scancel`.
- No existe SSH, transferencia remota ni gestión de credenciales.
- No hay selección científica de cutoff, k-grid, U, spin, carga, relajación o análisis electrónico.
- `BasicCampaignPlanner` valida orden/identidad, no construye aún un DAG general.
- La concurrencia multiproceso de writers queda fuera de M1; atomicidad no equivale a CAS/locking.
- `ArtifactStore` registra contenido producido por el fake; la importación remota y verificación de archivos externos queda futura.
- Reutilizar una asignación tras reiniciar supone que el proceso vive aún en el mismo contexto falso; reconciliación SLURM real queda futura.
- `DryRunFileSystem` es un planificador de mutaciones, no un filesystem virtual donde leer escrituras simuladas.

## Evidencia ausente

La validación remota es `NOT_RUN`. No se conoce el launcher SIESTA de Yoltla, módulos, versión, recursos ni comportamiento de restart. El estado científico permanece sin promoción: cero runs y outputs SIESTA.

## Próximo límite

M2 no está autorizado durante este trabajo. Un futuro adaptador mínimo deberá usar estas interfaces sin debilitar autorización, gates, path safety, persistencia o evidencia.

