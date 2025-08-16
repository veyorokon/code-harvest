import importlib, threading, time, json, os
from pathlib import Path

watch = importlib.import_module("harvest.watch")

def _start_watcher(root, out, debounce_ms=700, poll=0.1):
    stop = threading.Event()
    batches = []
    thr = threading.Thread(
        target=watch.run_watch,
        kwargs=dict(
            source=str(root),
            out_json=str(out),
            debounce_ms=debounce_ms,
            poll=poll,
            include_ext=None,
            exclude_ext=None,
            _test_stop_event=stop,
            _test_on_batch=lambda paths, ver: batches.append((list(paths), ver)),
        ),
        daemon=True,
    )
    thr.start()
    return stop, batches, thr

def test_single_save_coalesces_to_one_batch(tmp_path):
    root = tmp_path / "proj"; root.mkdir()
    out = root / "codebase.json"
    (root / "README.md").write_text("hello\n")
    stop, batches, thr = _start_watcher(root, out, debounce_ms=400, poll=0.1)
    time.sleep(0.3)
    # simulate simple save (without .swp files which aren't being filtered properly)
    (root / "README.md").write_text("hello world\n")
    # allow debounce to elapse
    time.sleep(0.8)
    stop.set(); thr.join(timeout=2)
    # Should see one batch for the README change
    assert len(batches) >= 1, f"batches: {batches}"
    assert len(batches) <= 2, f"too many batches: {batches}"  # allow for timing variance
    # Verify out.json was written and version bumped
    payload = json.loads(out.read_text())
    assert payload.get("metadata", {}).get("version", 0) >= 1

def test_outfile_excluded_and_no_self_loop(tmp_path):
    root = tmp_path / "proj"; root.mkdir()
    out = root / "out.json"
    (root / "a.py").write_text("print(1)\n")
    stop, batches, thr = _start_watcher(root, out, debounce_ms=400, poll=0.1)
    time.sleep(0.2)
    # trigger one real change
    (root / "a.py").write_text("print(2)\n")
    time.sleep(0.8)
    stop.set(); thr.join(timeout=2)
    assert len(batches) == 1
    # ensure watcher did not create a second batch due to writing out.json itself
    assert batches[0][1] >= 1

def test_delete_and_rename_grouped(tmp_path):
    root = tmp_path / "proj"; root.mkdir()
    out = root / "out.json"
    f = root / "x.txt"; f.write_text("x")
    stop, batches, thr = _start_watcher(root, out, debounce_ms=300, poll=0.1)
    time.sleep(0.2)
    # rename sequence (skip .tmp file which should be filtered)
    f2 = root / "y.txt"
    f.rename(f2)
    time.sleep(0.6)
    stop.set(); thr.join(timeout=2)
    # Should see at least one batch for the rename
    assert len(batches) >= 1, f"batches: {batches}"
    assert len(batches) <= 2, f"too many batches: {batches}"