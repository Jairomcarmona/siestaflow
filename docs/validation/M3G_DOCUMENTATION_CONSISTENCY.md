# M3G documentation consistency

The maintained public set comprises root README/changelog/contributing files; five user manuals; three operations guides; two scientific-governance guides; and three developer guides. Required primary paths and README links are tested.

The command-tree test walks `argparse` subparsers and verifies every command listed in `docs/user/CLI_REFERENCE.md` exists, including nested example-result and remote-environment imports. Representative `--help` calls and the documented generic validation command execute successfully. Exit `0`, exit `2`, dry-run behavior, and the distinctions `LOCAL`, `SIMULATED`, `PREVIEW`, `REMOTE_EVIDENCE_PENDING`, `REMOTE_VERIFIED`, and `SCIENTIFICALLY_AUTHORIZED` are documented.

The update policy is binding in `CONTRIBUTING.md`: CLI, flow, remote, state/gate, and visible changes respectively update CLI reference, user manual, Yoltla runbook, scientific governance, and changelog.

Result: `DOCUMENTATION_AS_CODE_PASS` and `CLI_DOCUMENTATION_CONSISTENCY_PASS`.
