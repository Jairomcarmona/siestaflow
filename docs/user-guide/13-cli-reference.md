# Referencia de CLI

`qraft` y `qraft --help` muestran la misma orientación de la versión instalada
y terminan sin abrir un prompt. Cada comando acepta `qraft COMANDO --help`.
Los errores de argumentos y preflight usan una salida distinta de cero.
`--json` está disponible donde se indica.

## Comandos principales

| Comando | Propósito | Uso habitual |
|---|---|---|
| `init [PATH]` | Crea un template editable de CampaignSpec. | `qraft init campaign.yaml` |
| `check TARGET` | Evalúa input/model, consistencia científica, evidencia numérica y entorno de ejecución mediante las autoridades existentes; no ejecuta el engine ni envía trabajo. | `qraft check campaign.yaml` |
| `run TARGET` | Ejecuta una campaña o cálculo que ya pasó `check` y conserva intentos. | `qraft run calc.fdf --runs-root .qraft-runs` |
| `status [TARGET]` | Consulta el progreso y la siguiente acción disponible. | `qraft status --runs-root .qraft-runs` |
| `resume [FDF]` | Continúa usando el estado de recuperación guardado. | `qraft resume calc.fdf --runs-root .qraft-runs` |
| `results [TARGET]` | Inventaría outputs registrados y dirige las exportaciones soportadas. | `qraft results` |
| `examples [TOPIC]` | Muestra temas de aprendizaje respaldados por fixtures. | `qraft examples` |

Las opciones disponibles dependen de cada comando. Consulte `qraft check --help`,
`qraft inspect plan --help`, `qraft run --help` y `qraft resume --help` antes
de combinar opciones de ejecución; `--json` está disponible donde la ayuda del
comando lo indica.

## Navegación canónica V2

La agrupación canónica introduce `setup` para entorno/configuración/perfiles,
`inspect` para FDF, inputs, reglas, pseudopotenciales y planes, y `advanced`
para las familias de arquitectura. Las rutas históricas siguen funcionando
durante la ventana de compatibilidad y escriben su aviso de migración en
stderr. Consulte `qraft setup --help`, `qraft inspect --help` y
`qraft advanced --help` para descubrir los hijos directos.

| Ruta canónica | Propósito | Uso habitual |
|---|---|---|
| `setup env` | Inspecciona capacidades instaladas de ejecución. | `qraft setup env --profile local` |
| `setup config` | Muestra la configuración efectiva y su procedencia. | `qraft setup config --profile local` |
| `setup profile` | Lista, muestra o valida perfiles de ejecución. | `qraft setup profile list` |
| `inspect plan TARGET` | Resuelve y muestra un plan sin enviarlo. | `qraft inspect plan calc.fdf --profile local` |
| `advanced campaign render TARGET` | Materializa variantes FDF sin ejecutar el engine. | `qraft advanced campaign render calc.fdf --output rendered` |

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
