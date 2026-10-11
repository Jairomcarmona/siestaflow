"""The selected U-Q6 alternative is explicit non-contractual diagnostics."""
from pathlib import Path


def test_cli_json_classification_is_explicit_for_platform_consumers():
    root = Path(__file__).resolve().parents[2]
    policy = (root / 'docs/developer/PUBLIC_API.md').read_text(encoding='utf-8')
    cli = (root / 'docs/user/cli.md').read_text(encoding='utf-8')
    assert 'CLI JSON compatibility decision (U-Q6)' in policy
    assert 'non-contractual diagnostic output' in policy
    assert '`check`, `status`, `run inspect`' in policy
    assert 'non-contractual diagnostic output' in cli
