# U-Q9 implementation status

Specification: DFT Lab ADR-017 including Adendas 1 and 2, merged through `9710b9e`, and
[issue #10](https://github.com/Jairomcarmona/siestaflow/issues/10).

## Independent value layer

`qraft.api.ControllerReservation` contains exactly the five reservation fields
from Adenda 1. Parsing rejects missing/unknown fields, coercions, unsupported
inner launchers, nonintegral per-node capacity, inner CPU values other than 1
and excessive concurrent inner shape. `resource_request` validates arithmetic
against an explicitly hosted `RuntimeAllocation` and returns an **ungranted**
host-exclusive request for the existing coordinator. It does not discover
capacity, assert scheduler authority, or change `ExecutionSpec`.

Historical pre-Adenda1 base `5eb7d61` (six-field type), Windows 11,
Python 3.12.10, uv 0.11.14: consumer/workflow/contract selection
133 passed (44.64 s). Independent reservation cases: 54 passed. The same wheel
was installed in fresh external environments on Windows and WSL Ubuntu,
Python 3.12.10. `python -I` ran those cases and the existing installed public
integration and packaged-controller fixtures, without checkout imports or
`PYTHONPATH`. Dependency installation used the hash-bearing export of `uv.lock`.

Wheel SHA-256:
`f76d696c84f263da7e0a0d55e4d3256f8ce4ee664326c4d9d5af1a12cfdfe9b3`.
No SIESTA/HubbardFlow job was submitted. These are value/transport tests, not
the seven controller acceptance tests or scientific qualification.

## Adenda 1 and 2 implementation

DFT Lab #52 and HubbardFlow #43 have normative resolutions in Adendas 1 and 2.
No extra descriptor fields or alternative recovery protocol are introduced.

The declared qraft.controller extension resolves only the installed distribution's
console script through importlib.metadata: no plugin discovery, entrypoint import
or PATH lookup. Reservation, ledger, resume-verdict and defs schemas are bundled
byte-identically, with SHA checks and offline validation. Explicit calendar checks
work without optional jsonschema format dependencies. Ledger evaluation preserves
native IDs and matches all 21 Adenda2 vectors, including shadow fallback; torn
JSONL lines are never silently dropped.

The installed isolated supervisor enables child subreaping before Popen and uses
pidfd (glibc fallback supported). ECHILD proves closure, including setsid and double
fork descendants. Owner publication and a process-lifetime OS lock precede Popen;
state sealing/closure evidence are independent of the runtime parent. Recovery
helpers reject unowned/tampered state and never treat PID absence as owner death.

Windows11/Python3.12.10: consumer/workflow/contracts plus new helper suites:
170 passed, 1 skipped/25.32s; namespace guard PASS/16 files. The same development
wheel, SHA256 c82aac79cd03efbff921d1a0970973645600404cad678ba88c2220d7814862ed,
was installed externally in Windows and WSL with a synthetic console-script wheel
and hash-bearing dependencies from uv.lock. Python -I/no PYTHONPATH: Windows rejects
native controllers; WSL verifies normal, escaped-descendant cancellation and exit75
fixtures, CLOSED/ECHILD and unrelated process untouched. This wheel came from an
uncommitted development snapshot: it is not a release pin or complete qualification.
No scientific job.

Read-only admission now resolves the declared installed entrypoint, selects the
runtime's unique allocated host, expands SLURM_JOB_CPUS_PER_NODE in allocation
host order, rejects profile overrides of scheduler evidence, and positively
probes pidfd/subreaping before any lease. Local CPU capacity remains the explicit
profile declaration. Windows11/Python3.12.10: the same selection with admission
cases gives 197 passed, 1 skipped/32.51s; legacy namespace guard remains PASS.
The installed synthetic supervisor fixture exercises this admission helper too.
This is not yet compiled-runtime integration or scheduler qualification.

[DFT Lab #57](https://github.com/Jairomcarmona/dftlab-suite/issues/57) asks for the
precise byte-identical 2.0 package guarantee. The current builder vendors runtime
source bytes, so an inert comment changes the ZIP, manifest and checksums despite
identical campaign/scientific inputs. A synthetic paired-package reproduction is
preserved; no old runtime duplication or hash omission is introduced.

Controller campaign2.1 preparation, compiled runtime reservation-map integration,
resource admission/release and finalization vetos are **not implemented or enabled**.
U-H7 integration, engine pinning and real HF-1 qualification remain pending.
Existing campaign loading still rejects `controller`. The complete U-Q9 PR must
remain draft, must not close #10 and must not merge until the integration gates and
all seven installed acceptance tests are resolved. HF-1 stays disabled.
