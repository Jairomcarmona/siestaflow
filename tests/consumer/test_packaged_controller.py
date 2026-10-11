"""An installed-source preparer must provide a complete standalone controller."""
import importlib.util
from pathlib import Path


def test_preparation_and_isolated_vendored_bindings():
    path = Path(__file__).parents[2] / 'tools/check_packaged_controller.py'
    spec = importlib.util.spec_from_file_location('packaged_consumer', path)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    fixture.check_packaged_controller(require_installed=False)
