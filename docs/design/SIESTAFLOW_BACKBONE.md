# SIESTAFLOW — columna vertebral del proyecto

Estado: guía arquitectónica viva  
Versión del documento: 1.0  
Software de referencia actual: SIESTAFLOW 0.2.0 alpha

## 1. Misión

SIESTAFLOW transforma una intención científica declarada en un workflow DFT
autocontenido, verificable y reproducible para entornos HPC.

No es un generador de scripts Bash. Su valor está en:

- representar dependencias científicas mediante un DAG tipado;
- transferir geometrías, parámetros y checkpoints con trazabilidad;
- automatizar decisiones numéricas previamente autorizadas;
- aprovechar una asignación Slurm sin intervención continua;
- detectar errores antes de consumir cómputo;
- conservar evidencia suficiente para reproducir y explicar cada resultado.

El investigador conserva siempre la autoridad sobre las decisiones físicas.

## 2. Límites

SIESTAFLOW no debe:

- elegir silenciosamente funcionales, Hubbard U, carga, spin o modelos;
- presentar una heurística como una ley física;
- modificar parámetros científicos durante una recuperación técnica;
- declarar validez científica basándose sólo en que un proceso terminó;
- depender de Codex, internet o un daemon en el nodo de login;
- ocultar los comandos, entradas o transformaciones ejecutadas.

## 3. Vocabulario estable

- **Project**: investigación completa y sus políticas.
- **Campaign**: conjunto relacionado de cálculos o barridos.
- **Workflow**: DAG científico declarativo.
- **Task**: nodo tipado del DAG.
- **Run**: ejecución concreta de un workflow resuelto.
- **Attempt**: intento individual de una tarea.
- **Artifact**: entrada o resultado con identidad, tipo, hash y procedencia.
- **Dependency**: relación de control o transferencia de datos.
- **Checkpoint**: estado reutilizable para continuar una tarea.
- **Evidence**: registro verificable de una ejecución o decisión.
- **Executor**: adaptador que ejecuta tareas en un entorno determinado.

## 4. Arquitectura

```text
CLI o futura interfaz gráfica
        ↓
Servicios de aplicación
        ↓
Compilador de workflows
        ↓
Contratos del núcleo
        ↓
Plugins y adaptadores
        ↓
SIESTA / Slurm / Hydra / posprocesadores
```

Las dependencias apuntan hacia los contratos del núcleo. La CLI, SIESTA,
Slurm y los plugins no deben acoplarse entre sí directamente.

La CLI local puede priorizar usabilidad. El runtime remoto debe mantenerse
pequeño, autocontenido y con dependencias mínimas.

## 5. DAG científico

Tipos iniciales de tarea:

- `calculation`
- `transformation`
- `validation`
- `sweep`
- `selection`
- `checkpoint`
- `postprocess`
- `comparison`
- `export`
- `external`

Las aristas transportan control o artefactos tipados. Un workflow dinámico
puede expandirse únicamente mediante reglas declaradas, deterministas y
acotadas. Antes de ejecutarse se materializa como `workflow.lock.json`.

## 6. Ciclo de uso objetivo

```bash
siestaflow environment check
siestaflow project init
siestaflow input validate --explain
siestaflow workflow validate
siestaflow workflow plan
siestaflow workflow graph
siestaflow workflow build
siestaflow run submit
siestaflow run status
siestaflow run diagnose
siestaflow run resume
siestaflow artifact lineage
siestaflow results compare
```

Todos los comandos relevantes deben ofrecer:

- ayuda comprensible;
- salida humana y `--json`;
- `--dry-run` cuando exista una mutación;
- códigos de salida estables;
- acciones idempotentes cuando sea posible;
- explicación y remediación de errores.

## 7. Fases de construcción

### Fase 0 — Contratos del núcleo

Contratos versionados para validación, artefactos, ejecución, eventos y
plugins. Compatibilidad mediante adaptadores.

**Cierre:** las capas superiores dependen de contratos, no de implementaciones.

### Fase 1 — Compilador de workflows

Modelo formal del DAG, tareas tipadas, validación estructural, resolución de
dependencias y generación determinista de `workflow.lock.json`.

**Cierre:** una misma definición produce el mismo DAG y el mismo hash.

### Fase 2 — CLI para investigadores

`environment check`, `project init`, validación explicable, planificación y
representación del grafo.

**Cierre:** un proyecto básico puede prepararse sin editar JSON manualmente.

### Fase 3 — Ejecutor autocontenido

Ejecución concurrente, artefactos, checkpoints, intentos, reanudación,
shutdown controlado, diagnóstico y reconciliación.

**Cierre:** el workflow padre → reinicio DM pasa una prueba real en Yoltla.

### Fase 4 — DAG adaptativo

Barridos, selectores matemáticos, fan-out/fan-in, convergencia adaptativa y
recuperaciones previamente autorizadas.

**Cierre:** un parámetro convergido se selecciona y propaga sin intervención
manual y con procedencia completa.

### Fase 5 — Optimización HPC

Perfiles de cluster, Slurm/Hydra, distribución interna de recursos,
aprovechamiento del walltime y continuación entre asignaciones.

**Cierre:** un DAG heterogéneo utiliza correctamente una asignación real.

### Fase 6 — Validación científica extensible

Reglas versionadas para FDF, pseudopotenciales, geometrías, periodicidad,
carga, spin, Hubbard, convergencia y posprocesamiento.

**Cierre:** toda regla declara alcance, evidencia, severidad y remediación.

### Fase 7 — Resultados y publicación

Linaje, comparaciones, tablas, reportes metodológicos y exportación de
evidencia para tesis y artículos.

**Cierre:** un resultado puede rastrearse hasta sus entradas y decisiones.

## 8. Invariantes

1. Ningún resultado se identifica sólo por su nombre de archivo.
2. Toda transferencia conserva hash, origen y destino.
3. Una entrada transferida y un archivo de trabajo mutable son artefactos
   distintos.
4. Ninguna tarea dependiente inicia antes de validar sus padres.
5. Ninguna recuperación cambia la física sin autorización explícita.
6. La terminación normal no implica validez científica.
7. Las decisiones automáticas registran regla, versión, métricas y evidencia.
8. La evidencia histórica no se reescribe; una reclasificación es un evento.
9. El paquete remoto funciona sin procesos persistentes en el login.
10. Un cambio incompatible requiere migración o nueva versión contractual.

## 9. Criterio para aceptar funcionalidades

Una funcionalidad entra al núcleo sólo si:

- evita un error costoso o elimina trabajo manual repetitivo;
- tiene un contrato independiente del motor o cluster;
- puede probarse de forma determinista;
- conserva trazabilidad;
- ofrece diagnóstico comprensible;
- no introduce una decisión científica oculta.

Si no cumple estos puntos, debe permanecer como plugin, ejemplo o política del
proyecto.

## 10. Proceso de entrega

Cada fase sigue el mismo ciclo:

1. especificación y contratos;
2. implementación mínima vertical;
3. pruebas unitarias;
4. prueba integral local;
5. paquete autocontenido;
6. prueba real en HPC;
7. registro de errores observados;
8. aceptación explícita;
9. publicación de versión cuando exista evidencia suficiente.

No se incrementa una versión únicamente porque el código compile o las pruebas
locales pasen.

## 11. Estado inmediato

La Fase 0 está implementada en una rama de arquitectura. El controlador actual
ya proporciona evidencia real sobre Hydra, dependencias, reinicio DM y
persistencia dentro de una asignación.

La Fase 1 dispone de una implementación vertical local: contrato del DAG,
validación estructural, resolución de artefactos, orden topológico, plan,
grafo y `workflow.lock.json` determinista. Su aceptación queda condicionada a
la suite completa y a revisión antes de conectar el lock con ejecución remota.
