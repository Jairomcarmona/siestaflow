# Fase 4.1 — corte adaptativo canónico local

## Objetivo

Establecer la ruta canónica y verificable para un DAG adaptativo pequeño:

```text
2–3 variantes ya materializadas
→ selector determinista
→ fan-in de la decisión
→ tarea final consumidora
```

La expansión es deliberadamente estática en la definición: las variantes son
nodos concretos antes de compilar y quedan bloqueadas en `workflow.lock.json`.
Así no se introduce una expansión dinámica opaca durante una asignación.

## Contrato de este corte

- Una variante usa `kind: sweep` y la capacidad
  `siestaflow.gate.deterministic-metric`. Produce un único JSON de métrica
  declarado como artefacto requerido.
- Un selector usa `kind: selection` y la capacidad
  `siestaflow.gate.minimum-selector` o
  `siestaflow.gate.maximum-selector`. Recibe entre dos y tres artefactos de
  variante, ordena por `(valor, variant_id)` y conserva todos los candidatos,
  la regla y el elegido en su artefacto de decisión.
- La tarea final de esta demostración usa `kind: transformation` y la
  capacidad `siestaflow.gate.selection-consumer`. Recibe el artefacto de
  decisión por una arista de artefacto: es el fan-in y propagación explícitos.
- `run prepare` los traduce a tareas `gate` hash-bound dentro del mismo
  `AllocationController`; no llama `sbatch`, SSH ni Yoltla.

## No objetivos

- No se cambia FDF, geometría, pseudopotenciales ni parámetros científicos.
- No se elige automáticamente un parámetro científico real.
- No se implementa todavía `converge_then_relax`, criterios con unidades,
  estabilidad consecutiva o una aceptación HPC de Fase 4.
- No se cierra Fase 4 con esta base local.

## Criterios de aceptación locales

1. El compilador conserva el fan-out, las aristas de artefacto y un orden
   estable en el lock.
2. El selector es determinista, conserva procedencia y desempata por
   `variant_id`.
3. Hash o JSON de métrica inválido bloquea el selector y la tarea final.
4. El paquete de `run prepare` contiene sólo scripts y entradas hash-bound;
   el `run.lock.json`, campaña y `submit.slurm` permanecen coherentes.
5. El controlador local ejecuta las variantes, selector y consumidor, y el
   resultado final identifica exactamente la variante seleccionada.
