import os
from pathlib import Path
from .constants import CANON_BASENAME, CANON_EXT

def resolve_reap_out(user_out: str|None, target: str = None) -> str:
    """
    Default output for reap uses directory name as harvest filename.
    e.g., harvest reap ./some/path/here → ./here.harvest.json (in current working dir)
    """
    if user_out:
        return os.path.abspath(user_out)
    
    # If target is provided and is a directory, use its name for the output file
    if target and os.path.isdir(target):
        dir_path = Path(target).resolve()
        dir_name = dir_path.name
        # Write to current working directory with directory name + .harvest.json
        return os.path.abspath(f"{dir_name}{CANON_EXT}")
    
    # Fallback to default behavior
    return os.path.abspath(CANON_BASENAME)

def resolve_data_path(arg: str|None, cwd: str) -> str:
    """
    For watch/serve: accept a file path or a directory.
    If a directory is given, resolve to <dir>/codebase.harvest.json.
    """
    p = os.path.abspath(arg or os.path.join(cwd, CANON_BASENAME))
    return os.path.join(p, CANON_BASENAME) if os.path.isdir(p) else p