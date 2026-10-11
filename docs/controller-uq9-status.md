# U-Q9 implementation status

Specification: DFT Lab ADR-017, merged at `812a0a5`, and
[issue #10](https://github.com/Jairomcarmona/siestaflow/issues/10).

## Independent value layer

`qraft.api.ControllerReservation` contains exactly the six reservation fields
from ADR-017. Parsing rejects missing/unknown fields, coercions, unsupported
inner launchers, nonintegral per-node capacity, inner CPU values other than 1
and excessive concurrent inner shape. `resource_request` validates arithmetic
against an explicitly hosted `RuntimeAllocation` and returns an **ungranted**
host-exclusive request for the existing coordinator. It does not discover
capacity, assert scheduler authority, or change `ExecutionSpec`.

Windows 11, Python 3.12.10, uv 0.11.14: consumer/workflow/contract selection
133 passed (44.64 s). Independent reservation cases: 54 passed. The same wheel
was installed in fresh external environments on Windows and WSL Ubuntu,
Python 3.12.10. `python -I` ran those cases and the existing installed public
integration and packaged-controller fixtures, without checkout imports or
`PYTHONPATH`. Dependency installation used the hash-bearing export of `uv.lock`.

Wheel SHA-256:
`f76d696c84f263da7e0a0d55e4d3256f8ce4ee664326c4d9d5af1a12cfdfe9b3`.
No SIESTA/HubbardFlow job was submitted. These are value/transport tests, not
the seven controller acceptance tests or scientific qualification.

## Open design gates

[DFT Lab issue #52](https://github.com/Jairomcarmona/dftlab-suite/issues/52)
records the cross-attempt identity contradiction and the escaped-descendant
proof problem, with a WSL reproduction, plus the allocation authority question.
The specification owner must resolve these; this branch introduces no extra
contract fields or alternative recovery protocol.

Controller campaign 2.1 admission, launcher, lease acquisition/release, entrypoint
resolution, ledger validation and recovery are **not implemented or enabled**.
U-H7 integration, engine pinning and real HF-1 qualification remain pending.
Existing campaign loading still rejects `controller`. The complete U-Q9 PR must
remain draft, must not close #10 and must not merge until the design gates and
all seven installed acceptance tests are resolved. HF-1 stays disabled.
