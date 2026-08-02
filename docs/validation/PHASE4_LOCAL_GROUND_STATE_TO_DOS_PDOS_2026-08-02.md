# Continuación estado electrónico → DOS/PDOS local — Fase 4

Fecha: 2026-08-02
Estado: `LOCAL_ELECTRONIC_CONTINUATION_VALIDATED`

## Dictamen

La receta `siestaflow.recipe.siesta.ground-state-to-dos-pdos` se ejecutó por la
ruta canónica con dos tareas SIESTA locales y una arista real de reinicio:

```text
ground_state
  → phase4_ground_state.DM
  → SHA-256 y evidencia de transferencia
  → phase4_dos_pdos_restart.DM
  → DOS/PDOS con DM.UseSaveDM T
```

El job Slurm local `44` terminó `COMPLETED`; ambas tareas se completaron en un
intento. El manifiesto del hijo prueba `dm_read_attempted: true` y
`dm_read_succeeded: true`.

## Invariantes comprobados

- El padre declara su DM como salida requerida.
- El hijo depende explícitamente del padre y no es elegible si el padre falla.
- La DM transferida conserva SHA-256
  `2a5aeb1cd735c116aa69fc48bd48a516c045a23bf029d8207b4a80211f53b475`.
- El nombre de la DM cambia de `phase4_ground_state.DM` a
  `phase4_dos_pdos_restart.DM` únicamente como destino de ejecución; la
  evidencia conserva el hash y el manifiesto de origen.
- El FDF hijo exige `DM.UseSaveDM T`; falta de esta directiva, cambios de carga
  u otra diferencia de identidad de reinicio bloquean la creación del workflow.
- El hijo produjo DOS y PDOS requeridos y verificados.

## Límites

Esto es evidencia técnica local, no una afirmación científica: el fixture es
Si de dos átomos y la ventana PDOS no está aprobada científicamente. La salida
incluye la advertencia Gamma sobre imágenes periódicas, por lo que no se
interpretan valores electrónicos. No se ejecutó Yoltla.

## Procedencia e integridad

Fuente limpia: `5bf39eed38b11fbef5c35db366e2df835debc0bf`.

| Elemento | SHA-256 |
|---|---|
| contenido de `workflow.lock.json` | `2fbb9fe34a29ec224b7ac620d7c82583ba1e534339366d1157fbafe30194c21e` |
| envelope de `workflow.lock.json` | `1147ae464003f1f183c25e87032b420013cd3714ed77657e8a4a89a78e4b9025` |
| contenido de `run.lock.json` | `f52a2760f22e90b40a20a17f7eca0d6f05bb81ccb3105aca98b68d54f84fb5b4` |
| envelope de `run.lock.json` | `83aad5ca7fd373078c25401c79658980a980a1409af764474973055e65b8902d` |
| DM transferida | `2a5aeb1cd735c116aa69fc48bd48a516c045a23bf029d8207b4a80211f53b475` |
| DOS hijo | `16ea4547a046c45b9f42027b8611c6d13a9770278bb94e59c79f8e1d189ea162` |
| PDOS hijo | `66ef86df42f770822e4ba37bba3cdc06bdde44b2726c5412f76be3256490e8a0` |
| ZIP autocontenido | `ac934699e60df5549d8ac58a747a6a5ef9d457eb644092473d1090311f67092f` |

## Verificaciones

```text
workflow preflight                    PASS, sin hallazgos
python verify_package.py              PASS
bash -n submit.slurm                  PASS
bash -n progress.sh                   PASS
python -m zipfile -t ZIP              PASS
sbatch --test-only submit.slurm       PASS
job 44                                COMPLETED, 2/2 tareas
result_manifest hijo                  transferencia y lectura DM verificadas
```

## Conclusión

SIESTAFLOW puede ahora ejecutar, de forma aislada o encadenada, el camino
estado electrónico → DOS/PDOS sin suponer compatibilidad por nombre de archivo
ni mezclar decisiones científicas con resolución de ejecución. El siguiente
corte útil es un consumidor de resultados (tabla/exportación reproducible), no
la interpretación automática de los espectros.
