import importlib
import inspect
import pytest

@pytest.mark.skipif("importlib.util.find_spec('harvest.ui') is None", reason="UI module not present")
def test_ui_contains_auto_refresh_markers():
    ui = importlib.import_module("harvest.ui")
    src = inspect.getsource(ui)
    assert "searchParams.set('v'" in src
    assert "cache: 'no-store'" in src
    assert "autoRefresh" in src