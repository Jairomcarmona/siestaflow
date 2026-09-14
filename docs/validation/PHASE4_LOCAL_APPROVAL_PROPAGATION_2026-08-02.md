# Propagación local de aprobación numérica — Fase 4

Fecha: 2026-08-02
Estado: `LOCAL_TECHNICAL_CHAIN_COMPLETED`

## Dictamen

La cadena canónica local se completó de extremo a extremo:

```text
observaciones SIESTA reales
→ informe de convergencia
→ decisión humana explícita
→ perfil numérico hash-bound
→ WorkflowDefinition converge_then_relax
→ workflow.lock.json
→ run prepare
→ run.lock.json
→ paquete autocontenido
→ Slurm local
→ relajación SIESTA real
```

El resultado demuestra la propagación técnica y trazable de un parámetro aprobado
(`Mesh.Cutoff = 80 Ry`) a una relajación CG. No es una convergencia científica
publicable: la regla usó tolerancias deliberadamente laxas y una celda de Si de
dos átomos exclusivamente como *fixture* de integración de bajo coste.

## Alcance y límites

- No se ejecutó Yoltla ni se reclama equivalencia HPC.
- No se cambiaron entradas científicas de un proyecto del usuario.
- El pseudopotencial Si PSML proviene del archivo de referencia proporcionado por
  el usuario y queda protegido por SHA-256 dentro de cada paquete.
- La aprobación fue autorizada por el usuario solo para esta validación técnica;
  no debe reutilizarse como decisión científica de producción.
- La Fase 4 continúa abierta: faltan recuperaciones autorizadas, consumidores
  DOS/bandas/óptica y aceptación remota del flujo completo.

## Ejecuciones y evidencia

| Artefacto | Resultado |
|---|---|
| SIESTA local, mallas 60/80/100 Ry y primer control eggbox | job Slurm local `20`, 4/4 tareas completadas |
| Evaluador adaptativo inicial | job `24`, solicitó correctamente eggbox de 80 Ry |
| SIESTA local, control eggbox de 80 Ry | job `26`, completado |
| Evaluación limpia de la evidencia | job `31`, `READY_FOR_HUMAN_REVIEW`, candidato 80 Ry |
| `converge_then_relax` limpio | job `33`, `COMPLETED`, 1/1 tarea y salida SIESTA `Job completed` |

El trabajo `22` no se usa como evidencia de aceptación: reveló que
`SystemName`/`SystemLabel` técnicos se estaban incluyendo erróneamente en la
identidad física. El defecto se corrigió en el commit fuente limpio siguiente.

## Procedencia de la cadena final

Fuente limpia: commit `2664eba` (`fix(observations): ignore technical system labels`).

| Elemento | Ruta local | SHA-256 |
|---|---|---|
| Informe de convergencia | `.siestaflow-work/phase4-local-mesh-technical/mesh-convergence-report-clean.json` | `95c33001a65dabd0ff57291730dd685abe0217c02f915ff085ea1a8a50ce58b3` |
| Decisión envelope | `.siestaflow-work/phase4-local-mesh-technical/mesh-approval-clean.json` | `69733cfd5bbf5165914ebc6a6dbc86aac8749da4ad55b6e76364dd8f9519b248` |
| Perfil envelope | `.siestaflow-work/phase4-local-mesh-technical/mesh-profile-clean.json` | `04c103061cd9d66aa3cb940bf2f5d5f9002a261316f6c9bf74d7ea85f10c6eeb` |
| `workflow.lock.json` envelope | `.../packages/phase4-local-technical-converge-then-relax-clean/workflow.lock.json` | `bcfedbb8e397511171bdc29d68c817913cdd95f118da2621bbc7ec90c77dffd6` |
| `run.lock.json` envelope | `.../packages/phase4-local-technical-converge-then-relax-clean/run.lock.json` | `b3e6faf0e8434882733eefbe3dd84be34b719be3cce0760759760eaeee60ca91` |
| Paquete autocontenido | `.../packages/phase4-local-technical-converge-then-relax-clean.zip` | `b4de7fc579c6c929e0d722a0053cff15c1d845c0cc2499f5327a5a6a7ffb1e0e` |

El `campaign.yaml` del paquete final registra `scientific_propagation` con:

- `approval_id`: `phase4-local-technical-mesh-approval-clean`
- `profile_id`: `phase4-local-technical-mesh-80-ry-clean`
- parámetro: `Mesh.Cutoff`
- hash de evidencia, decisión, perfil y candidato.

La tarea `relax_structure` solicitó 1 rank, ejecutó el FDF de 80 Ry y produjo
un manifiesto de resultado validado por hash:
`f72612a49c4b01b87662339ff82393feeab88c336e764156b476a71936a862f1`.

## Verificaciones aplicadas

```text
python -m pytest -q                 439 passed
python -m compileall -q src         PASS
git diff --check                    PASS
python verify_package.py            PASS
bash -n submit.slurm                PASS
bash -n progress.sh                 PASS
sbatch --test-only submit.slurm     accepted by Slurm local
sbatch submit.slurm                 job 33 COMPLETED (0:0)
```

## Conclusión

Queda demostrada localmente la ruta de control: la selección no se inyecta como
un flag de motor, sino que se conserva como procedencia aprobada y el FDF
verificado debe reflejar el valor seleccionado. El mismo patrón puede alimentar
futuros fragmentos de k-grid, DOS, bandas u óptica sin codificar un material o
una campaña concreta en el núcleo.
