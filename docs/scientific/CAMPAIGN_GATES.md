# Campaign gates

The built-in registry contains `TechnicalCompletionGate`, `KnownWarningsGate`, `ArtifactPresenceGate`, `SCFConvergenceGate`, `HumanReviewGate`, and `ParameterSeriesCompletionGate`. Each evaluates named evidence and returns `PASS`, `REVIEW`, `BLOCKED`, or `FAIL` without importing a project module.

Project-specific rules belong in package policies or registered plugins. A declarative campaign can name general gates in metadata; adding a gate implementation requires explicit registration and tests. Gate success never supplies scientific interpretation or authorization.
