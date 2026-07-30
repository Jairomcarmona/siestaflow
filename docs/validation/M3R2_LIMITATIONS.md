# M3R2 limitations

- No V3 command was executed remotely and no job was submitted.
- The sanitized fixture demonstrates scheduler resolution, not scientific suitability or a production SIESTA profile.
- Missing or `N/A` access policies block automatic resolution; an administrator may need to provide additional evidence.
- Dynamic reservations, TRES/GRES, preemption, QoS time caps beyond visible policy fields, and site-specific submit filters are not inferred.
- V2 evidence may only be reused through an explicit provenance- and hash-preserving importer; V3 currently prioritizes a clean login-probe rerun.
