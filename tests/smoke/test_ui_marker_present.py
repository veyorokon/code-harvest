import importlib
import inspect
import pytest

@pytest.mark.skipif("importlib.util.find_spec('harvest.ui') is None", reason="UI module not present")
def test_ui_contains_update_badge_marker():
    ui = importlib.import_module("harvest.ui")
    src = inspect.getsource(ui)
    assert "harvest-update-tip" in src or "Updated — click to refresh" in src