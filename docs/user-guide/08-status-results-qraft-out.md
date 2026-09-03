# Estado, resultados y `qraft.out`

```bash
qraft status --runs-root .qraft-runs
qraft status --runs-root .qraft-runs --json
```

El estado compacto muestra Campaign, Progress, Convergence, Selected point, Technical y Scientific. Los estados que puedes observar son `NOT STARTED`, `RUNNING`, `INTERRUPTED`, `FAILED` y `COMPLETED`.

`qraft.out` es el resumen humano de la campaña. Ábrelo primero para identificar el comando ejecutado, progreso, selección, caminos de input/output y el resultado. Para automatización usa `status --json`, `campaign-result.json` y los manifiestos de attempt.

Orden recomendado de diagnóstico:

1. `qraft status`.
2. `.qraft-runs/qraft.out`.
3. `campaign-result.json` o `qraft status --json`.
4. `work/.../attempt-XXXX/stderr.txt` y `stdout.txt`.

No confundas `COMPLETED` de ejecución con una conclusión científica: revisa también `Technical` y `Scientific`.
