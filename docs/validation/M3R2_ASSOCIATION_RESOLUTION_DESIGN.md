# M3R2 association resolution design

The standard-library resolver models explicit, account-wide, QoS-only, incomplete, and contradictory association scopes. Parsers retain source file, line, observation time, and evidence status; invalid rows produce diagnostics.

Candidates are the intersection of observed associations, visible partitions, UP policies, account/QoS restrictions, node bounds, and walltime bounds. The resolver returns every compatible candidate and rejection reason. Automatic selection is limited to exactly one compatible default. Multiple defaults, no candidates, and candidates without a unique default remain explicit stopped states. Human input is accepted only as an exact candidate match.

`ALL` is permissive only for an already observed association. `N/A` and missing restrictions are distinct and conservatively non-selectable.
