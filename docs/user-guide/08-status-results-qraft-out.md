# Estado, resultados y `qraft.out`

Consulta siempre el mismo directorio persistente que pasaste a `run`:

```bash
qraft status --runs-root "$RUNS_ROOT"
qraft status --runs-root "$RUNS_ROOT" --json
qraft results --runs-root "$RUNS_ROOT"
qraft results --runs-root "$RUNS_ROOT" --json
```

`status` proyecta el estado registrado del runtime canónico. Su vista compacta
muestra `STATE`, `PROGRESS`, `LAST STEP` y `NEXT ACTION`; entre los estados
posibles están `NOT_STARTED`, `RUNNING`, `INTERRUPTED`, `FAILED`, `BLOCKED`,
`COMPLETED`, `UNKNOWN` y `UNREADABLE`. La salida JSON es la interfaz adecuada
para automatización.

`results` es un inventario, no una nueva validación científica. Los elementos
marcados como `PRESENT` corresponden a archivos que realmente existen, como
`workflow_runtime.json`, `attempt.json`, `stdout.txt`, `stderr.txt` y los
outputs de SIESTA. El inventario también puede mostrar un artefacto esperado
como `NOT_EVALUATED` cuando no existe. `campaign-result.json` puede existir en
protocolos de campaña, pero no es obligatorio en una ejecución de un único
FDF.

`qraft.out` es el resumen humano acumulado de la sesión. Ábrelo para revisar el
comando, configuración resuelta, rutas, intentos, recuperación y validación
técnica:

```bash
less "$RUNS_ROOT/qraft.out"
```

Orden recomendado de diagnóstico:

1. `qraft status --runs-root "$RUNS_ROOT"`.
2. `$RUNS_ROOT/qraft.out`.
3. `qraft results --runs-root "$RUNS_ROOT" --json`.
4. `$RUNS_ROOT/runtime/*/state/workflow_runtime.json`.
5. `$RUNS_ROOT/runtime/*/work/*/attempt-*/stderr.txt` y `stdout.txt`.

Si `status` informa `INTERRUPTED`, vuelve a entrar en una asignación compatible
y ejecuta:

```bash
qraft resume --runs-root "$RUNS_ROOT"
```

El estado `COMPLETED` describe la ejecución registrada. Comprueba también la
validación técnica y realiza la revisión científica correspondiente antes de
usar los resultados como evidencia física.
