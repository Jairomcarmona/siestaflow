# Exportación reproducible local de DOS/PDOS — Fase 4

Fecha: 2026-08-02  
Estado: `LOCAL_HASH_BOUND_RESULT_EXPORT_VALIDATED`

## Alcance

Se añadió el consumidor de solo lectura:

```text
results dos-pdos PACKAGE --output DIRECTORY
```

No reejecuta SIESTA, no modifica el paquete, no modifica FDF/PSML/DM y no
extrae conclusiones científicas. Antes de exportar, verifica el paquete
inmutable, el estado `COMPLETED`, el manifiesto de intento, terminación normal,
SCF convergido, y los SHA-256 de DOS/PDOS. Si el análisis consume una DM, exige
además evidencia de que SIESTA la leyó.

## Ejecución local

Se consumió el paquete local completado de la receta encadenada
`ground_state → DM → dos_pdos` (job local `44`) sin lanzar un cálculo nuevo:

```text
python -m siestaflow.cli results dos-pdos PACKAGE --output EXPORT --json
```

Resultado:

```text
DOS_PDOS_RESULT_EXPORTED
task_id: dos_pdos
rows: 61
columns: energy_eV,total_dos_states_per_eV
scientific_interpretation: NOT_PERFORMED
```

La salida produjo `total_dos.csv` y `dos_pdos_export.json`.

| Elemento | SHA-256 |
|---|---|
| tabla `total_dos.csv` | `f9c62a35c09be20c250fd0b5f398e11b7405f68b2e0a7d31dad2edf7f7870011` |
| manifiesto de exportación | `b6e21fb9e1c3c42c1b2b1f817f219c7adfb8abea63edb8d0e908680e805c40ca` |
| DOS fuente | `16ea4547a046c45b9f42027b8611c6d13a9770278bb94e59c79f8e1d189ea162` |
| PDOS fuente | `66ef86df42f770822e4ba37bba3cdc06bdde44b2726c5412f76be3256490e8a0` |
| DM transferida | `2a5aeb1cd735c116aa69fc48bd48a516c045a23bf029d8207b4a80211f53b475` |

El manifiesto conserva la evidencia `dm_read_attempted: true` y
`dm_read_succeeded: true`, además de los locks del workflow y run. PDOS queda
como artefacto bruto con hash; no se aplana ni se asignan proyecciones en esta
fase.

## Límite explícito

La tabla es una exportación técnica reproducible. La selección de ventana,
ancho, malla, espín, interpretación de picos, gap, y orbitales continúa siendo
una decisión científica humana. Esta ejecución local de Si de dos átomos no se
usa como evidencia de una propiedad científica.
