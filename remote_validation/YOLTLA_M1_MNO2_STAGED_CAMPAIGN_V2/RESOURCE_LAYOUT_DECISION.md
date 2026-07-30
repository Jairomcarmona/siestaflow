# Decisión de layout de recursos

| Layout | Eficiencia por cálculo | Throughput de campaña | Complejidad | Riesgo de afinidad | Riesgo científico | Evidencia |
|---|---|---|---|---|---|---|
| 1×80 | Posible saturación para 54–79 átomos | Una corrida a la vez | Media, cruza dos nodos | Medio | Bajo para la entrada; alto si se asume eficiencia | Sin benchmark remoto |
| 2×40 | Hipótesis equilibrada, una corrida/nodo | Dos corridas simultáneas | Baja-media | Bajo con slots 0–39 por nodo | Bajo; resultados siguen independientes | Topología local probada, rendimiento no |
| 4×20 | Menor paralelismo por cálculo | Hasta cuatro corridas | Alta | Mayor: dos rangos por nodo | Bajo si no hay interferencia de memoria/I/O | Topología local probada, rendimiento no |

Decisión inicial: `dual_40`, explícitamente
`PROPOSED_REQUIRES_SCALING_EVIDENCE_AND_HUMAN_ACCEPTANCE` en la plantilla.
Se propone porque evita que un sistema pequeño use 80 rangos, mantiene una
corrida por nodo y ofrece dos cálculos de throughput con afinidad sencilla.
No es una afirmación de eficiencia.

La calibración 20/40/80 es técnica, usa la misma entrada M1 estática y no puede
interpretarse como energía científica. También tiene una limitación: el sistema
de 54 átomos no representa necesariamente las relajaciones de 73/79 átomos.
Por eso la V2 registra mediciones pero no cambia el layout automáticamente.

Condición para cambiar: evidencia remota reproducible de tiempo de pared,
CPU-time, ubicación, afinidad y hashes, seguida de aceptación humana. Un cambio
del perfil invalida por SHA-256 cualquier materialización previa.
