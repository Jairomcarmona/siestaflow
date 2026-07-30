# Auditoría V1 → V2

| Hallazgo | Gravedad | Archivo afectado | Corrección V2 | Prueba | Riesgo residual |
|---|---:|---|---|---|---|
| Perfil remoto dentro de contenido inmutable | Alta | `profiles/`, documentación | Derivados solo en `site/profiles/`; plantilla permanece inmutable | `test_mutable_site_profiles...`, verificador de cobertura | Evidencia remota aún debe capturarse |
| Solicitud Slurm antigua/no sustentada | Crítica | perfil y `submit.slurm` | qz2d-128p, 2 nodos, 80 tareas, 40/nodo, 2 días, vini/normal | `test_qz_profile...`, `test_site_profile...` | Disponibilidad temporal |
| Walltime no aceptaba días | Alta | validadores | Parser estricto para `HH:MM:SS`, `HHH:MM:SS`, `D-HH:MM:SS` | `test_walltime...` | Ninguno local |
| Distribución implícita 64+16 posible | Crítica | `submit.slurm` | `--ntasks-per-node=40` y relaciones exactas | `test_site_profile...` | Slurm remoto debe confirmarlo |
| Confusión asignación/paso MPI | Crítica | perfil/controlador | Layouts 1×80, 2×40 y 4×20 separados de 2×40 de la reserva | `test_resource_layouts...` | Eficiencia no medida |
| Acoplamiento exclusivo a `srun` | Crítica | runtime | Abstracción `SrunLauncher`/`HydraSshLauncher`; candidato Hydra SSH | `test_srun_and_hydra...` | Compatibilidad real requiere Yoltla |
| Sin preflight dentro del ticket | Crítica | `submit.slurm` | Prueba de hosts, SIESTA MPI, entradas, escritura, capacidad y topología | `test_runtime_preflight...` | Binding físico debe auditarse remotamente |
| Versión declarada pero no exigida | Crítica | perfil/controlador | Conserva `required_siesta_version`; comparación exacta antes del FDF y vía MPI | `test_siesta_version...` | Formato real de salida se valida remotamente |
| Evidencia remota incompleta | Alta | captura | Captura Slurm, QoS, nodos, módulos, Hydra/srun y solicitud exacta | sintaxis Bash y validación `profilectl` | Política del sitio puede cambiar |
| Comandos de módulo como texto arbitrario | Alta | perfil/preflight | Esquema estructurado `purge` + lista segura `load` | `test_qz_profile...` | Requiere entorno Modules funcional |
| Reintentos bloqueados en la asignación | Alta | controlador | Reintentos retryable, backoff, límite y directorios por intento | `test_retry_occurs...`, `test_deterministic...` | Clasificación depende de salida real |
| Contabilidad solo global de CPU | Crítica | controlador | `ResourceManager` por host y rangos contiguos | `test_resource_layouts...` | Afinidad remota debe comprobarse |
| Fuente de fin de ticket no garantizada | Alta | Slurm runtime | End time, start+limit, `scontrol`, fallback conservador; registra fuente | `test_walltime_margin...` | Variables disponibles dependen de Yoltla |
| Un ticket solo cubría una fase | Alta | campaña | Bundles de asignación con dependencias internas | `test_site_profile...` | Paradas científicas siguen creando tickets |
| Sanity y malla separados pese a gate objetiva | Media | grafo | Gate técnica automática fail-closed; no aceptación científica | dependencia/postcondición en test de bundle | Parser real puede revelar advertencias ambiguas |
| Malla seleccionaba implícitamente k-grid | Crítica | flujo | k-grid en bundle aparte después de F3A humana | estado/graph auditado | Costo de una segunda espera en cola |
| Procedencia duplicada/no determinista | Alta | materializador | Comentarios previos eliminados; una sola política; sin timestamp | `test_materialization...` | Ninguno local |
| F0 podía prefabricarse | Crítica | gates | Solo borrador con `decision=null`; aceptación es comando explícito | inspección y gate guard | Responsabilidad humana permanece |
| PSML externos en V1 | Alta | distribución | Por instrucción directa, Mn/O incluidos e inmutables con hashes exactos | `test_scientific_structure...`, tamper test | Licencia/distribución debe conservarse |
| Manifest V1 quedaría inválido tras cambios | Crítica | empaquetado | Identidad V2, manifiesto y ZIP reconstruidos por herramientas | `verify_package.py` + SHA-256 final | Ninguno local |
| Posible envío automático | Crítica | todos los scripts | Solo existe `sbatch --test-only`; envío real documentado como manual | `test_no_automatic_sbatch...` | Error humano fuera del paquete |

Dictamen: la lógica local es `PASS`; el despliegue es
`BLOCKED_BY_REMOTE_EVIDENCE`; las fases científicas posteriores son
`BLOCKED_BY_SCIENTIFIC_DECISION`.
