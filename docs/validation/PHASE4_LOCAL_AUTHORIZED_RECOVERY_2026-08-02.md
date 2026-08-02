# Recuperación autorizada local — Fase 4

Fecha: 2026-08-02
Estado: `LOCAL_RECOVERY_VALIDATED`

## Dictamen

Se validó una recuperación real, controlada y fail-closed sobre el mismo
workflow canónico `converge_then_relax` ya validado localmente. La interrupción
no se simuló dentro del controlador: fue una señal `SIGTERM` enviada por Slurm
local durante un paso SIESTA en ejecución.

```text
workflow.lock.json inmutable
→ run prepare con perfil recovery-v1 (max_attempts = 2)
→ job 37, SIGTERM durante relax_structure
→ estado y manifiesto del intento 1 persistidos
→ run resume bloqueado hasta confirmación terminal explícita
→ job 38, nueva asignación
→ intento 2 de la misma tarea
→ manifiesto y hashes verificados
→ COMPLETED
```

## Resultado observado

| Trabajo local | Estado | Evidencia |
|---|---|---|
| `37` | `INTERRUPTED` | `SIGTERM`, tarea `relax_structure` en `INTERRUPTED`, intento `1` |
| inspección sin confirmación | `PREVIOUS_JOB_TERMINAL_CONFIRMATION_REQUIRED` | no emitió comando de reenvío |
| inspección con confirmación | `RESUBMISSION_REQUIRED` | emitió únicamente `sbatch submit.slurm` |
| `38` | `COMPLETED` | nueva asignación, intento `2`, salida SIESTA y manifiesto validados |

El estado final conserva ambas asignaciones (`37`, `38`), no modifica el
workflow y registra el manifiesto final de resultado:
`5d38864558e9d51b7dd54153bd7a739f800fe21aa934b1efd110de877c575f7a`.

## Límites de autorización

El perfil `local-real-siesta-serial-recovery-v1` autorizó exclusivamente dos
intentos para esta validación técnica local. No habilita reintentos ilimitados,
no relanza tareas completadas, no recupera fallos científicos de manera
automática y no constituye autorización científica ni remota.

El controlador revalida el estado checksum-wrapped, los manifiestos de intento,
las entradas y los artefactos antes de aceptar una tarea previa como completada.
La reanudación desde CLI es de solo lectura: nunca ejecuta `sbatch`; la persona
operadora debe confirmar que el trabajo anterior llegó a estado terminal.

## Procedencia e integridad

Fuente limpia: commit `89eaf0c72060156099b6a0d927b09c91c2a7b043`.

| Artefacto | SHA-256 |
|---|---|
| contenido de `workflow.lock.json` | `c46d8145ee7078db2be3f90ef17693c0d9dda38426fa737be66505038abbd5ca` |
| envelope de `workflow.lock.json` | `bcfedbb8e397511171bdc29d68c817913cdd95f118da2621bbc7ec90c77dffd6` |
| contenido de `run.lock.json` | `5c8894e502cf978ce872b510b5f8b6adf710a77c259f9c74ecb986013a1cf154` |
| envelope de `run.lock.json` | `36ad772d4f38dcd57df00d44393fe73bd78607a9c11b2f7b60f2e1d90a4744c2` |
| `campaign.yaml` | `526841b38f1bd1c68f80b82c36e2ab7d388d01c35e9dae064e34d0a5974c7cfe` |
| paquete ZIP | `eba8ec39a1c8e6759ec73577af5fa0f3ca8e45bbe0cab03b0c316d348e62cf66` |

Paquete local: `.siestaflow-work/phase4-local-mesh-technical/packages/phase4-local-technical-recovery-interrupted`.

## Verificaciones

```text
python verify_package.py              PASS antes de ejecutar
bash -n submit.slurm                  PASS
bash -n progress.sh                   PASS
python -m zipfile -t ZIP              PASS
sbatch --test-only submit.slurm       PASS
job 37                                interrupción real observada
run resume                            confirmación terminal obligatoria
job 38                                COMPLETED; intento 2 verificado
```

## Conclusión

La recuperación autorizada ya está integrada en la ruta canónica, no como una
ruta paralela de empaquetado. La Fase 4 continúa abierta: siguen pendientes los
fragmentos consumidores (DOS, bandas, óptica) y una aceptación remota de un
flujo científico completo bajo reglas científicas no técnicas.
