# Release checklist

- [ ] version and CHANGELOG reviewed
- [ ] license/authors/maintainers metadata intentionally set or tracked as debt
- [ ] focused tests pass
- [ ] complete suite passes or baseline-only exception is documented
- [ ] `python -m compileall -q src`
- [ ] `python -m build` creates wheel and sdist
- [ ] wheel contents inspected; no scratch, worktrees, results, ZIPs or secrets
- [ ] clean venv installs wheel without checkout/PYTHONPATH
- [ ] installed `import qraft`, `qraft --version`, and `qraft --help`
- [ ] installed `env`, `config`, profile and validate smoke
- [ ] installed single_fdf plan/run/recovery smoke
- [ ] installed REPL starts and exits cleanly
- [ ] profile lookup works from project and user configuration roots
- [ ] standalone package fallback regression smoke
- [ ] `git diff --check`
- [ ] staged file list and commit scope audited
- [ ] no generated `dist/`, venv, evidence or test temporary data committed

Release artifacts are built from a clean commit. Publishing to PyPI is a
separate, explicitly authorized operation.
