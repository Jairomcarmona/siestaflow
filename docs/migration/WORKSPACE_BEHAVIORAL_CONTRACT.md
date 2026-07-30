# Contrato conductual de proyecto y workspace

## Conductas observadas

- Centinela y descubrimiento ascendente (`ProjectManager.find_root`).
- Árbol semántico de inputs, pseudos, runs, results, scripts y logs.
- Nombres `{label}_{calculation}` con colisiones `_v02`…`_v99`.
- `job_index.map` actualizado por temp+replace.
- staging por copia/symlink y metadata de creación.
- Dos fallos caracterizados: etiquetas `../` escapan de `03_runs`; `_copy_dir` sobrescribe archivos homónimos.

## Contrato futuro

`PROJECT_MANAGER` posee identidad, versión de esquema, raíz y referencias a campañas. `WORKSPACE_MANAGER` materializa un plan autorizado, nunca decide física. Toda ruta derivada se resuelve y verifica como descendiente de su raíz antes de crear, copiar, enlazar, reemplazar o borrar.

Estructura conceptual mínima:

```text
project/
├── project.json
├── inputs/              # fuentes importadas, con hash
├── pseudos/             # manifest; binarios opcionales según política
├── campaigns/<id>/
│   ├── plan.json
│   ├── tasks/<task-id>/
│   ├── state/
│   ├── events/
│   └── artifacts/
└── packages/
```

## Reglas normativas

1. IDs y nombres se validan con esquema/slug; se rechazan absolutos, `..`, separadores, dispositivos y colisiones case-insensitive.
2. Crear es `fail-if-exists` por defecto. Reusar exige identidad y hash compatibles. No existe “force overwrite” para evidencia.
3. Staging es transaccional: directorio temporal hermano, manifest completo, fsync cuando aplique y rename final.
4. Copias registran origen lógico, tamaño, SHA-256 y método. Symlinks sólo si una política explícita los permite y su destino queda registrado.
5. Los manifests usan rutas relativas portables; jamás almacenan el checkout local como requisito remoto.
6. Cada intento tiene ID único. Outputs no conviven con contexto, snapshot ni inputs canónicos.
7. No se crea ni modifica geometría, FDF científico o pseudopotencial sin una autorización distinta a la operación de workspace.

## Deploy y provenance

`REMOTE_VALIDATION_PACKAGER` crea un paquete autocontenido para transferencia manual: manifest, hashes, instrucciones, configuración candidata marcada `UNVERIFIED_FOR_SIESTA` y pruebas fake. No incluye credenciales ni automatiza SSH. Importar resultados verifica el manifest, conserva bytes originales y genera una auditoría local separada.

## Recuperación ante colisión o interrupción

- Colisión semántica: asignar una nueva revisión/attempt de forma atómica; nunca elegir por `exists()` seguido de escritura sin exclusión.
- Copia interrumpida: el staging incompleto no se promueve.
- Manifest corrupto: `BLOCKED`, no reconstrucción silenciosa.
- Symlink roto o input cambiado: `REVIEW`/`FAIL` según política; no reparación automática.

## Pruebas mínimas migradas

Confinamiento adversarial, colisiones concurrentes, case-folding, symlink escape, falta de espacio, copia interrumpida, hashes, no-overwrite, portabilidad de manifest e importación idempotente. `test_workspace_contract.py` captura el baseline y dos defectos del donante.

