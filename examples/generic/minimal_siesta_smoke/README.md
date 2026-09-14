# Minimal generic SIESTA smoke

This executable package proves that species and parameter values are supplied by data. It is synthetic, contains no pseudopotential binaries, and makes no scientific claim.

```powershell
python -m qraft.cli examples validate generic/minimal_siesta_smoke --json
python -m qraft.cli examples run generic/minimal_siesta_smoke --campaign-id mesh_series --json
```
