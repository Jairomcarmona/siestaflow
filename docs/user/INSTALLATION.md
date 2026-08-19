# Installation

## Normal installed mode

QRAFT requires Python 3.11+. SIESTA, MPI and a scheduler are external
capabilities; their absence does not prevent package installation.

```bash
python -m venv .venv
source .venv/bin/activate
pip install qraft-0.2.0-py3-none-any.whl
qraft --version
qraft --help
qraft env
```

The wheel is the official user path. A checkout and `PYTHONPATH` are not
required. Cluster users install the wheel once in a venv or Python module; each
campaign then carries scientific inputs/configuration and evidence, not a copy
of `src/qraft`.

## Development mode

```bash
git clone https://github.com/Jairomcarmona/siestaflow.git
cd siestaflow
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## Standalone fallback

Historical controller packages remain supported for clusters where installing
a wheel is impossible. They are a deployment fallback, not the normal user
workflow. Never mix a standalone runtime copy with an installed runtime in the
same campaign invocation.

License and maintainer metadata are intentionally not guessed; see
`docs/developer/TECH_DEBT.md` before a public registry release.
