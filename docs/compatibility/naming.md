# QRAFT naming and compatibility

The product name is **QRAFT**. The Python distribution, import package and
command are already `qraft`:

```bash
python -c "import qraft"
qraft --help
```

The repository currently uses the historical GitHub name
[`Jairomcarmona/siestaflow`](https://github.com/Jairomcarmona/siestaflow).
That repository URL is intentional; it does not change the installed package
name. Clone instructions and package metadata must use the actual repository
location. Update those links together if the repository is renamed, after
checking the new location and affected integrations.

## Persistent identifiers

The `siestaflow.*` namespace remains part of the compatibility surface. For
example, `siestaflow.engine.siesta` identifies an engine capability and
`siestaflow.workflow-definition` identifies a contract. These values are used
by code and serialized data; they are not spelling errors in the product name.

Preserve contract, artifact, plugin, producer and rule identifiers, together
with locks, manifests and historical evidence. Changing an identifier may
change identity checks, compatibility with existing runs or derived hashes.
Historical file names and references must continue to identify the original
evidence, including references that contain `SIESTAFLOW`.

A repository-wide replacement of `siestaflow` with `qraft` is therefore unsafe.
Branding edits should select specific prose or URL occurrences and review the
complete diff. A future namespace migration needs an explicit compatibility
and migration design, an ADR and the validation required by
[development governance](../developer/DEVELOPMENT_GOVERNANCE.md).

## Namespace check

From the repository root, run:

```bash
python tools/check_legacy_namespace.py
```

This check compares the legacy namespace inventory in `src/qraft` by file,
identifier and occurrence count against its reviewed baseline. It helps detect
accidental replacement, removal or relocation of the recorded identifiers.
Do not refresh the baseline merely to make a failing check pass; review why
the inventory changed and whether a compatibility decision is required.

The check has a deliberately limited scope. It does not validate every
serialized format, historical artifact, contract semantic or hash, and equal
counts do not prove equal behavior. Keep the existing tests and independent
diff review. See the [safe publication workflow](../developer/SAFE_PUBLICATION.md)
for backup, verification and release preparation.
