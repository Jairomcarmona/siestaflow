# Convergencia

Para `MeshCutoff: 80, 100, 120 Ry`, QRAFT ejecuta cada punto, extrae la energía por átomo y aplica el criterio de `campaign.yaml`.

```yaml
values: [80, 100, 120]
# ...
delta: 0.01
unit: eV
consecutive: 1
```

El resultado tiene dos dimensiones:

- **technical PASS:** los intentos generaron evidencia técnica suficiente.
- **CONVERGED:** las métricas cumplen el criterio y QRAFT puede seleccionar un `MeshCutoff`.

Por ello `technical PASS` no equivale siempre a convergencia científica. Un resultado `SCIENTIFIC_NOT_CONVERGED` es válido: inspecciona `convergence.csv`, amplía o modifica científicamente el barrido y ejecuta una campaña nueva. No fuerces una selección editando resultados.

Cuando hay convergencia, consulta el punto elegido con:

```bash
qraft status --runs-root .qraft-runs
qraft status --runs-root .qraft-runs --json
```

El JSON es apropiado para scripts; el estado compacto es apropiado para lectura humana.
