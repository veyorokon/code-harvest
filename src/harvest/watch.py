#!/usr/bin/env python3
# Minimal watch mode: portable polling watcher with zero dependencies
from __future__ import annotations
import os, time, json, threading
from typing import Dict, Tuple, List, Optional, Callable
from pathlib import Path
from .constants import CANON_EXT

IGNORED_DIRS = {".git", ".hg", ".svn", "__pycache__", ".idea", ".vscode", ".tox", "node_modules", "dist", "build"}
IGNORED_FILES = {
    ".DS_Store", "Thumbs.db", ".swp", ".swo", ".bak", 
    "test-watch.json", "test-watch.json.tmp"  # ignore our own output files
}
IGNORED_PATTERNS = {".#", "#", "~", ".tmp", ".part", ".crdownload"}  # editor temp file patterns

def _filter_ext(path: str, only: Optional[set], skip: Optional[set]) -> bool:
    """Filter files by extension."""
    _, ext = os.path.splitext(path)
    ext = (ext[1:] if ext.startswith(".") else ext).lower()
    
    # Check if file should be ignored
    filename = os.path.basename(path)
    
    # Hard ignore of canonical harvest files regardless of include/skip
    if filename.endswith(CANON_EXT):
        return False
    
    if filename in IGNORED_FILES:
        return False
    if any(filename.startswith(pattern) or filename.endswith(pattern) for pattern in IGNORED_PATTERNS):
        return False
    
    if only and ext not in only: return False
    if skip and ext in skip: return False
    return True

def _is_ignored_name(filename: str) -> bool:
    """Check if filename should be ignored based on patterns."""
    if filename in IGNORED_FILES:
        return True
    return any(filename.startswith(pattern) or filename.endswith(pattern) for pattern in IGNORED_PATTERNS)

def _snapshot(root: str, only: Optional[set], skip: Optional[set], ignored_paths: Optional[set] = None) -> Dict[str, Tuple[int, int]]:
    """Create filesystem snapshot: path -> (mtime_ns, size)."""
    snap: Dict[str, Tuple[int, int]] = {}
    for base, dirs, files in os.walk(root):
        # Skip ignored directories  
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for fn in files:
            p = os.path.join(base, fn)
            if not _filter_ext(p, only, skip): continue
            # Check if path is in ignored set (for output files)
            if ignored_paths and os.path.abspath(p) in ignored_paths: continue
            try:
                st = os.stat(p)
                snap[p] = (st.st_mtime_ns, st.st_size)
            except OSError:
                continue
    return snap

def _write_atomic(path: str, payload: dict) -> None:
    """Atomic write via temp file."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def _bump_version(payload: dict) -> int:
    """Increment metadata.version and update timestamp."""
    meta = payload.setdefault("metadata", {})
    v = int(meta.get("version", 0)) + 1
    meta["version"] = v
    meta["generated_at"] = int(time.time())
    return v

def _incremental_reharvest(prev_payload: dict, changed_paths: List[str], current_snapshot: Dict[str, Tuple[int, int]]) -> dict:
    """
    Attempt incremental re-harvest of changed paths.
    Falls back to returning previous payload if incremental not available.
    """
    try:
        # Try to import and use incremental harvesting if available
        from .core import HarvestEngine
        
        # Get current file set from snapshot
        current_files = set(current_snapshot.keys())
        
        # Get previous file set from harvest data
        prev_files = {entry["path"] for entry in prev_payload.get("data", [])}
        
        # Determine what changed
        deleted_files = prev_files - current_files
        
        if deleted_files:
            print(f"[harvest] removing deleted files: {sorted(list(deleted_files))[:3]}{' (+more)' if len(deleted_files) > 3 else ''}")
        
        # Extract previous settings from metadata
        meta = prev_payload.get("metadata", {})
        source_info = meta.get("source", {})
        root = source_info.get("root", ".")
        
        # Create engine with default settings (could be made configurable)
        engine = HarvestEngine()
        
        # For now, do a full re-harvest of the root directory
        # In a more sophisticated implementation, this would only re-process changed files
        new_payload = engine.harvest_local(root)
        
        # Calculate deltas
        old_count = len(prev_payload.get("data", []))
        new_count = len(new_payload.get("data", []))
        
        # Update metadata with delta information
        new_payload["metadata"]["delta"] = {
            "added": max(0, new_count - old_count) if not deleted_files else 0,
            "removed": len(deleted_files),
            "changed": len([p for p in changed_paths if p in current_files])
        }
        
        # Preserve any custom metadata fields
        new_payload["metadata"].update({
            k: v for k, v in meta.items() 
            if k not in ("created_at", "delta", "counts", "schema")
        })
        
        return new_payload
        
    except FileNotFoundError as e:
        # Handle case where files are temporarily missing (editor operations)
        print(f"[harvest] file temporarily unavailable: {e.filename or 'unknown'} (retrying next cycle)")
        return prev_payload
    except Exception as e:
        print(f"[harvest] incremental error: {e!r} (keeping previous state)")
        return prev_payload

def run_watch(source: str, out_json: str, debounce_ms: int, poll: float,
              include_ext: Optional[str], exclude_ext: Optional[str],
              _test_stop_event: Optional[threading.Event] = None,
              _test_on_batch: Optional[Callable[[List[str], int], None]] = None) -> None:
    """Run the watch loop with portable polling."""
    
    # Parse extension filters
    only = set(e.strip().lower() for e in include_ext.split(",")) if include_ext else None
    skip = set(e.strip().lower() for e in exclude_ext.split(",")) if exclude_ext else None
    
    # Load or initialize payload
    payload = {
        "metadata": {
            "version": 0, 
            "source": {"type": "local", "root": os.path.abspath(source)},
            "schema": "harvest/v1.2"
        }, 
        "data": [], 
        "chunks": []
    }
    
    if os.path.exists(out_json):
        try:
            with open(out_json, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            print(f"[harvest] could not load existing {out_json}: {e}")
    
    # Initial harvest if file doesn't exist
    if not os.path.exists(out_json):
        print(f"[harvest] initial harvest of {source}")
        initial_snapshot = _snapshot(source, only, skip, set())
        payload = _incremental_reharvest(payload, [], initial_snapshot)
        _bump_version(payload)
        _write_atomic(out_json, payload)
        print(f"[harvest] created {out_json}")

    # Create ignored paths set to prevent self-triggering
    ignored_exact = {os.path.abspath(out_json), os.path.abspath(out_json) + ".tmp"}
    
    # Start watching
    prev = _snapshot(source, only, skip, ignored_exact)
    pending: set[str] = set()
    change_count = 0
    last_fire = 0.0
    
    print(f"[harvest] watching {source} → {out_json} (poll={poll}s, debounce={debounce_ms}ms)")
    print("[harvest] press Ctrl+C to stop")
    
    try:
        while True:
            if _test_stop_event is not None and _test_stop_event.is_set():
                break
            time.sleep(poll)
            cur = _snapshot(source, only, skip, ignored_exact)
            
            # Track additions and modifications
            for p, meta in cur.items():
                if p not in prev or prev[p] != meta:
                    pending.add(p)
            
            # Track deletions
            for p in prev.keys():
                if p not in cur:
                    pending.add(p)
            
            now = time.time()
            if pending and (now - last_fire) * 1000 >= debounce_ms:
                # Group rapid changes
                change_count += 1
                if change_count <= 3:  # Only report first few changes details
                    print(f"[harvest] detected changes: {sorted(pending)[:3]}{' (+more)' if len(pending) > 3 else ''}")
                paths = sorted(pending)
                pending.clear()
                last_fire = now
                
                try:
                    payload = _incremental_reharvest(payload, paths, cur)
                    ver = _bump_version(payload)
                    _write_atomic(out_json, payload)
                    print(f"[harvest] updated {out_json} → v{ver} ({len(paths)} files)")
                    if _test_on_batch:
                        try:
                            _test_on_batch(paths, ver)
                        except Exception:
                            pass
                except Exception as e:
                    print(f"[harvest] update error: {e!r}")
            
            prev = cur
            
    except KeyboardInterrupt:
        print(f"\n[harvest] stopped watching {source}")