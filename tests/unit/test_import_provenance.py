from pathlib import Path

import siestaflow


def test_import_origin_is_current_checkout():
    checkout = Path(__file__).resolve().parents[2]
    imported = Path(siestaflow.__file__).resolve()

    assert checkout / "src" in imported.parents
    assert imported == checkout / "src" / "siestaflow" / "__init__.py"

