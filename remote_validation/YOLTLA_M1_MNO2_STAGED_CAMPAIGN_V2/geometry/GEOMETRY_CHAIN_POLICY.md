# Política de encadenamiento geométrico

## Autoridad y evidencia

Para una relajación aceptada se conservan cinco piezas ligadas por SHA-256:
`run.fdf`, `siesta.out`, `*.STRUCT_OUT`, `*.XV` y `*.FA`.

1. `STRUCT_OUT` aporta la estructura final expresada por SIESTA y asociada a la
   última evaluación de fuerzas.
2. `XV` se analiza de forma independiente como estado de reinicio. Sus vectores
   y coordenadas están en bohr y se convierten con
   `1 bohr = 0.529177210903 Å`.
3. La promoción se rechaza si `STRUCT_OUT` y `XV` difieren más de `1e-6 Å`
   aplicando imagen mínima periódica. Por tanto, la transferencia no depende de
   parsear coordenadas impresas de manera redondeada en `siesta.out`.
4. `FA` debe conservar índices 1..N y demostrar la tolerancia de fuerza
   adoptada. La terminación normal y el estado SCF se toman de `siesta.out`.

## Identidad atómica

Nunca se copian directamente los índices de especie de un cálculo padre. Se
mapea cada átomo mediante `(número atómico, etiqueta química)` hacia
`ChemicalSpeciesLabel` del FDF destino. Deben coincidir:

- número total de átomos;
- composición e inventario;
- secuencia de elementos y linaje por índice;
- celda y unidades;
- orden de fragmentos definido en el contrato del sistema.

Cualquier discrepancia bloquea la generación.

## M1 y los complejos

```text
M1 semilla (54) ──relajación/aceptación──> M1 aceptado (54)
                                               ├──> F6 electrónica
                                               ├──┐
Ca(H2O)8 aceptado (25) ──────────────────────────┴──> M1-Ca8w semilla (79)
Mg(H2O)6 aceptado (19) ──────────────────────────┬──> M1-Mg6w semilla (73)
                                               └── M1 aceptado (54)
```

Los primeros 54 átomos de cada semilla M1-Ca/Mg pertenecen a M1 y conservan su
marco de celda. El clúster hidratado relajado se ajusta rígidamente a la
posición y orientación de su fragmento en la semilla mediante una rotación
propia y traslación; así se preservan sus distancias internas relajadas sin
perder el modo OS inicial. Después se revisan colisiones periódicas y
distancias cruzadas.

La herramienta `scripts/geometry_transfer.py` escribe sólo bajo `generated/`.
Los FDF maestros y los resultados padres son de sólo lectura.

## Compuertas

- F5 requiere celda fija, fuerza final aceptada, topología Mn–O e inventario.
- F6 consume únicamente el M1 promovido por F5.
- F7 requiere además padres Ca8w/Mg6w aceptados, FDF ejecutables auditados,
  convención de carga +2 y decisión de sensibilidad lateral.
- Una geometría interrumpida puede servir como reinicio tras validar su `XV`,
  pero no se promueve como geometría científica aceptada.

