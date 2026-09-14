# Fase 4.2 — regla general de convergencia de malla

## Alcance

`MeshConvergenceRule` expresa una política científica en datos de proyecto; el
nucleo no contiene especies, valores de cutoff ni tolerancias particulares. La
primera instancia de referencia es `MESH_CUTOFF_CONVERGENCE_M1_V1`, pero el
contrato se reutiliza cambiando el perfil y volviendo a someterlo a autoridad
científica humana.

El flujo lógico es un DAG adaptativo acotado:

```text
serie PRIMARY declarada (fan-out)
→ EVALUATE (fan-in)
→ [EGGBOX del candidato → EVALUATE]
  o [serie de extensión declarada → EVALUATE]
→ READY_FOR_HUMAN_REVIEW o REVIEW_REQUIRED
```

Las expansiones no son nombres de partición ni decisiones implícitas: el
evaluador devuelve las tareas siguientes con cutoff, baseline y desplazamiento.
No produce `PASS` científico, no propaga el cutoff a otro workflow y no ejecuta
SIESTA, Slurm, SSH o procesos persistentes.

## Criterio general

- Referencia: el nivel más alto de la onda completa evaluada.
- Energía: diferencia absoluta respecto a la referencia, normalizada por el
  número de átomos y expresada en `meV/atom`.
- Fuerzas: máxima norma de la diferencia vectorial atómica respecto a la
  referencia, en `eV/Ang`.
- Deben satisfacer simultáneamente los umbrales un número configurable de
  niveles consecutivos con mallas reales distintas.
- SCF fallido, inversión de la firma magnética, unidades incorrectas, identidad
  atómica/pseudopotencial inconsistente o evidencia incompleta bloquean la
  selección.
- Se confirma el candidato con una observación `EGGBOX` enlazada explícitamente
  a su baseline. Si falla, se prueba el siguiente candidato elegible.
- Si la serie inicial no basta, únicamente se solicitan los niveles de extensión
  declarados. Si tampoco bastan, el resultado es `REVIEW_REQUIRED`.
- La salida máxima es `READY_FOR_HUMAN_REVIEW`; elegir el valor definitivo sigue
  siendo una decisión humana.

## Perfil M1 inicial

El perfil de ejemplo declara `200, 250, 300, 350, 400 Ry`, extensión
`450, 500 Ry`, tolerancias `1 meV/atom` y `0.01 eV/Ang`, dos niveles
consecutivos y desplazamiento eggbox de media celda de malla. Sigue siendo
`synthetic_only`; no altera el FDF de referencia ni autoriza un cálculo real.
