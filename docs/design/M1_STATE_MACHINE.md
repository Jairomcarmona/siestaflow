# Máquina de estados M1

## Camino nominal

```text
PLANNED → PREPARED → RUNNING → COMPLETED
```

Cada flecha produce primero un `EventRecord`; luego se actualiza `CampaignState` mediante escritura atómica. Sólo un `GateDecision.PASS` produce `COMPLETED` y permite avanzar.

## Caminos de detención

| Evidencia | Decisión | Estado | Efecto |
|---|---|---|---|
| warning desconocido | REVIEW | REVIEW | stop; nunca auto-PASS |
| fallo inequívoco | FAIL | FAILED | stop |
| autorización/tiempo insuficiente | BLOCKED | BLOCKED | no launcher; sin intento para esa tarea |
| proceso interrumpido | BLOCKED | INTERRUPTED | stop; reanudable con nuevo intento |
| output truncado/ambiguo | REVIEW | REVIEW | stop para evidencia humana |

## Reanudación

1. Cargar `state.json`, verificar schema/hash y comparar con replay de eventos.
2. Convertir cualquier `RUNNING` recuperado a `INTERRUPTED` con evento explícito.
3. No lanzar tareas `COMPLETED`.
4. Una tarea `INTERRUPTED` autorizada recibe `attempt_N+1`; el intento previo queda intacto.
5. Estados `REVIEW`, `FAILED` o `BLOCKED` no continúan automáticamente.

## Consistencia

`EventStore.reconstructed_states()` valida `previous_state` en cada línea. `assert_matches()` rechaza divergencia entre el último evento y el snapshot. El diseño deriva de `PERSISTENCE_BEHAVIORAL_CONTRACT.md` y reemplaza `_advance_phase()` donor, que no validaba transiciones ni replay.

## Asignación

El allocation se crea una vez y su ID se persiste. Una reanudación local con asignación activa reutiliza el mismo ID. La campaña nominal termina la asignación con accounting `COMPLETED`; una salida de cola sin accounting permanece sin resolver.

