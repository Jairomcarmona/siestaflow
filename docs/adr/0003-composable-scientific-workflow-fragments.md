# ADR 0003 — Fragmentos científicos componibles y ciclos seleccionados por el usuario

## Estado

Aceptado para la base local de Fase 4. No autoriza cálculos científicos ni
cierra la fase.

## Contexto

El investigador debe poder ejecutar una operación aislada —por ejemplo,
convergencia, relajación o un análisis— o seleccionar una cadena completa. Un
flujo fijo obligaría a ejecutar trabajo innecesario; comandos especializados
con lógica propia duplicarían el motor y romperían la ruta canónica.

Las recetas existentes de Mesh, k-grid y producción de observaciones ya crean
un `WorkflowDefinition`, pero cada una materializaba por separado la envoltura
completa y los tipos científicos de sus entradas sólo eran implícitos.

## Decisión

Una capacidad de authoring aporta uno o más `WorkflowFragment`. Cada fragmento
contiene tareas ordinarias y contratos tipados para sus puertos de entrada. El
`WorkflowComposer`:

1. combina exclusivamente los fragmentos seleccionados por el usuario;
2. exige identidades de fragmento y tarea únicas;
3. verifica tipo de artefacto y media type en cada conexión producida;
4. rechaza una fuente externa reutilizada con tipos científicos incompatibles;
5. persiste fragmentos, puertos y conexiones en metadata canónica;
6. devuelve un `WorkflowDefinition` schema 1.0 que continúa por el compilador y
   `run prepare` sin rutas nuevas.

El vocabulario de tipos es abierto mediante identificadores namespaced. El
nucleo no contiene nombres de materiales, composiciones ni listas cerradas de
cálculos. Nuevos consumidores, incluidos bandas, DOS/PDOS, óptica o fonones,
pueden declarar tipos nuevos sin modificar el compositor.

Los perfiles numéricos distinguen autoridad `PROVISIONAL` y `APPROVED`. Un
perfil aprobado requiere una aprobación humana enlazada. La relajación podrá
usar un perfil provisional si el usuario lo elige explícitamente, conservando
esa clasificación en la procedencia.

## Límite de las decisiones humanas

Una selección científica posterior no muta un lock existente. El recorrido
completo se representa como etapas enlazadas:

```text
convergencia -> reporte -> aprobación humana
             -> nuevo intent/WorkflowDefinition/lock -> relajación -> análisis
```

La interfaz puede presentar esto como un ciclo completo, pero cada etapa
ejecutable sigue siendo inmutable y verificable.

## Compatibilidad

- Se conserva `WorkflowDefinition` schema 1.0.
- Se conservan los identificadores y parámetros de las recetas existentes.
- Mesh, k-grid y el productor de observaciones usan ahora el compositor.
- El compilador, `run prepare` y `AllocationController` no cambian de ruta.
- Los paquetes y locks históricos no se reescriben.

## No objetivos de este corte

- Implementar relajación, bandas, DOS/PDOS u óptica.
- Añadir materiales o pseudopotenciales al núcleo.
- Autorizar propagación automática de resultados científicos.
- Ejecutar aceptación remota.
