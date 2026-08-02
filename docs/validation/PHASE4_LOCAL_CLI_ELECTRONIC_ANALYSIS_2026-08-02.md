# Integración CLI de análisis electrónico — Fase 4

Estado: `LOCAL_ELECTRONIC_ANALYSIS_INTEGRATION_VALIDATED`

La receta genérica
`siestaflow.recipe.siesta.ground-state-to-electronic-analysis` se creó,
preflightó, compiló, preparó y ejecutó desde CLI por la ruta canónica. El
fixture técnico fue Si de dos átomos, pero el núcleo no contiene su nombre ni
sus parámetros.

```text
ground_state COMPLETED
├─ bands     COMPLETED, DM leída
├─ dos_pdos  COMPLETED, DM leída
└─ optics    COMPLETED, DM leída
```

Job Slurm local: `52`; campaña `COMPLETED`, 4/4, un intento por tarea.
Las tres ramas recibieron la DM con SHA-256
`2a5aeb1cd735c116aa69fc48bd48a516c045a23bf029d8207b4a80211f53b475`
y enlazaron el mismo manifiesto de resultado padre
`ef74d57537b3b356cd880b2244175dc2a07c2051e83e3139844923eabc8ec86f`.

| Elemento | SHA-256 |
|---|---|
| workflow lock | `0f3a40be72f0fc39d168452551d89ec855c97656746f3a6e5b4f087066864391` |
| run lock | `2131089e3790ef3a0481908e28c24c887a29c7152de1ffc5cc8598b8c17d1e08` |
| DM padre | `2a5aeb1cd735c116aa69fc48bd48a516c045a23bf029d8207b4a80211f53b475` |
| bands | `82eab56e1c01e964189d03961574e60a4d59b45e9a946c5a16008930e304cd4a` |
| DOS | `16ea4547a046c45b9f42027b8611c6d13a9770278bb94e59c79f8e1d189ea162` |
| PDOS | `66ef86df42f770822e4ba37bba3cdc06bdde44b2726c5412f76be3256490e8a0` |
| EPSIMG | `532a33e54029bcaecb399a3ba63275fc1353fa7fbb1d96b175d8fc6908e69af4` |
| ZIP local | `2d88263a9efb56b1cce630598a057ae11d406d6c73e827ab5b7730ec3ef3afa9` |

Los tres comandos `results` consumieron este único paquete y produjeron tablas
verificadas. La clasificación es `TECHNICAL_CLI_INTEGRATION_ACCEPTANCE` y la
interpretación científica es `NOT_PERFORMED`.
