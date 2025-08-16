import importlib, os
from pathlib import Path

watch = importlib.import_module("harvest.watch")

def test_snapshot_ignores_dirs_and_out(tmp_path):
    root = tmp_path / "proj"
    (root / "node_modules").mkdir(parents=True)
    (root / "dist").mkdir()
    (root / "src").mkdir()
    (root / "src" / "ok.py").write_text("print(1)")
    (root / "node_modules" / "ignore.js").write_text("x")
    out = tmp_path / "out.json"
    out.write_text("{}")
    ignored = {str(out.resolve()), str(out.resolve()) + ".tmp"}
    snap = watch._snapshot(str(root), only=None, skip=None, ignored_paths=ignored)
    # Only src/ok.py should be seen
    paths = set(p for p in snap.keys())
    assert any("src/ok.py" in p for p in paths)
    assert not any("node_modules" in p for p in paths)
    assert not any("dist" in p for p in paths)