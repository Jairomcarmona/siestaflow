# Version and compatibility policy

QRAFT uses semantic package versions. During `0.x`, public APIs may evolve with
minor releases; patch releases fix compatible defects. `1.0` will freeze the
documented public CLI/Python contracts. After 1.0, breaking public changes
require a major version, compatible features a minor version, and fixes a patch.

Persistent schemas are versioned independently from the package. Known major
versions are read according to their contract. Unknown major versions fail
closed with a clear error. Unknown compatible minor fields may be preserved or
ignored only where that schema explicitly permits it.

Old manifests, evidence, profiles, `qraft.out` and standalone packages are not
promised eternal support. Evidence is never silently rewritten or migrated.
Migration tools, when introduced, must create new output and preserve the
original bytes.
