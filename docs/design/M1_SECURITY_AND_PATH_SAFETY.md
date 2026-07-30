# Seguridad y path safety M1

## Identificadores

`validate_identifier()` acepta sólo ASCII alfanumérico inicial seguido de alfanuméricos, `_`, `-` o `.`. Rechaza vacío, `.`/`..`, controles, rutas absolutas, letras de unidad, `/`, `\`, `../` y `..\`.

`safe_join()` valida cada componente, resuelve la ruta y comprueba que el resultado sea descendiente de la raíz autorizada. Las pruebas cubren traversal POSIX y Windows.

## No sobrescritura

- `write_text` abre con modo exclusivo salvo solicitud interna explícita.
- `copy` falla si el destino existe.
- proyecto y attempt fallan ante colisión.
- nuevos intentos usan `attempt_001`, `attempt_002`, etc.
- sólo `StateStore` reemplaza su snapshot mediante operación atómica deliberada.

## Dry-run

`DryRunFileSystem` no parchea funciones globales. Lecturas consultan disco; mkdir/write/copy/remove/atomic/append sólo agregan `FileOperation`. La prueba inventaría SHA-256 antes y después y obtiene igualdad exacta.

## Autorización antes de efectos

El envelope completo se verifica antes de crear campaña o allocation. Para cada tarea, alcance y tiempo se comprueban antes de crear su directorio de intento o llamar launcher. Hash alterado/vigencia expirada bloquean. Una tarea individual no autorizada no obtiene workspace ni ejecución.

## Imports

La prueba de provenance compara `siestaflow.__file__` resuelto con `<checkout>/src/siestaflow/__init__.py`; detectaría un paquete global, editable ajeno u otro checkout. Esto responde a la contaminación observada durante M0.

## Datos sensibles y comandos

M1 no maneja credenciales, SSH ni tokens. `TaskSpec.command` se almacena como tuple, pero `LocalFakeLauncher` no lo ejecuta. No existe interpolación shell ni llamada a `subprocess`.

