# Concurrency and Resource Model

The model is derived from `ExecutionSpec.allocated_cpus`,
`ResourceRequest`, and `ResourceCoordinator`; it does not simulate an HPC
cluster or infer real nodes.

| Setting | P=1 | P=4 |
| --- | ---: | ---: |
| Synthetic task MPI ranks | 1 | 1 |
| CPU units per task | 4 | 4 |
| Node units per task | 1 | 1 |
| Allocation CPU units | 4 | 16 |
| Allocation node units | 1 | 4 |
| `max_parallel_steps` | 1 | 4 |
| Hosts | none | none |

The fixture launcher is not registered as host-aware, so `exclusive_hosts` is
false. Node units still matter: `try_acquire` subtracts every lease's nodes
from the allocation even when no host is assigned. Therefore an allocation of
one node could not demonstrate four simultaneous runtime leases.

P=4 evidence:

- `peak_parallel_steps=4`
- `peak_active_launches=4`
- `peak_cpus=16`
- `peak_nodes=4`
- same-N P=1/P=4 summary SHA-256 values match exactly

The validation launcher uses a constant 20 ms synthetic delay and a one-time
four-worker rendezvous solely to make the existing runtime leases observable.
It does not launch MPI, create a second runtime, alter the DAG, or affect the
derived candidate metric. State writes remain peak-concurrent=1 because the
canonical runtime lock serializes them.
