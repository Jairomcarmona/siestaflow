# Referencia de CLI

`qraft --help` es la autoridad de la versión instalada. Cada comando acepta
`qraft COMANDO --help`; use `qraft` y luego `cli` para ver la misma superficie
desde la interfaz interactiva. Los errores de argumentos y preflight usan una
salida distinta de cero. `--json` está disponible donde se indica.

## Comandos principales

| Comando | Propósito | Uso habitual |
|---|---|---|
| `init [PATH]` | Crea un template editable de CampaignSpec. | `qraft init campaign.yaml` |
| `env` | Inspecciona capacidades instaladas de ejecución. | `qraft env --profile local` |
| `config` | Muestra la configuración efectiva y su procedencia. | `qraft config --profile local` |
| `profile` | Lista, muestra o valida perfiles de ejecución. | `qraft profile list` |
| `validate FDF` | Valida el FDF y ejecuta el preflight no ejecutable. | `qraft validate calc.fdf --siesta /ruta/siesta` |
| `plan FDF` | Resuelve y muestra el plan de tres nodos. | `qraft plan calc.fdf --profile local` |
| `render FDF` | Materializa variantes FDF sin ejecutar el engine. | `qraft render calc.fdf --output rendered` |
| `run FDF` | Ejecuta una campaña de un FDF y conserva intentos. | `qraft run calc.fdf --runs-root .qraft-runs` |
| `status` | Consulta el estado de una campaña de un FDF. | `qraft status --runs-root .qraft-runs` |
| `resume [FDF]` | Reanuda o reutiliza una sesión guardada. | `qraft resume calc.fdf --runs-root .qraft-runs` |

Los argumentos recurrentes de `validate`, `plan`, `run` y `resume` incluyen
`--partition`, `--nodes`, `--np`, `--cpus-per-rank`, `--launcher`, `--siesta`,
`--profile` y `--json` donde aplique. Los launchers actuales son `direct`,
`hydra`, `openmpi` y `srun`.

## Comandos avanzados

Estas familias son capacidades soportadas para preparación reproducible,
workflows, evidencia y transferencia; no son necesarias para una corrida local
de un solo FDF. Consulte siempre el `--help` específico antes de usarlas.

| Comando | Cuándo usarlo | Subcomandos importantes |
|---|---|---|
| `project` | Preparar o inspeccionar un paquete de proyecto reproducible. | `init`, `inspect`, `validate`, `load` |
| `fdf` | Inspeccionar la representación analizada de un FDF. | `inspect` |
| `input` | Aplicar el validador SIESTA o consultar sus reglas versionadas. | `validate`, `rules` |
| `pseudo` | Verificar manifiestos y hashes de pseudopotenciales. | `verify` |
| `campaign` | Crear, validar, simular, observar o ejecutar el worker de una campaña de controlador. | `create`, `validate`, `simulate`, `status`, `progress`, `watch` |
| `workflow` | Autorizar, validar, preflight, planificar, visualizar y compilar una definición de workflow. | `recipes`, `create`, `compose`, `validate`, `preflight`, `plan`, `graph`, `compile` |
| `scientific` | Registrar una decisión revisada y materializar su perfil numérico aprobado. | `decide`, `profile` |
| `results` | Exportar tablas verificadas de DOS/PDOS, bandas u óptica desde un paquete terminado. | `dos-pdos`, `bands`, `optics` |
| `examples` | Inspeccionar, validar, preparar, empaquetar o importar resultados de ejemplos. | `list`, `inspect`, `validate`, `stage`, `package`, `run`, `results import` |
| `remote` | Crear paquetes de transferencia o importar evidencia sin enviar trabajos. | `package`, `controller-package`, `results import`, `environment package`, `environment import` |

`run` también contiene herramientas avanzadas de paquetes hash-bound y Slurm:
`prepare`, `candidates`, `discover`, `resources`, `placement`,
`snapshot-import`, `inspect`, `status` y `resume`. Estas herramientas no hacen
una reserva ni envían `sbatch`; una selección de recursos debe provenir de la
evidencia Slurm que el comando solicita o importa.

Los adaptadores internos no forman parte de la interfaz pública. El resultado
científico no se infiere por la CLI; revise la evidencia y los artefactos que
produzca cada comando.
