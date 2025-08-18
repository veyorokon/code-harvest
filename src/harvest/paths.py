import os
from .constants import CANON_BASENAME

def resolve_reap_out(user_out: str|None, cwd: str) -> str:
    """Default output for reap is a visible file in CWD."""
    return os.path.abspath(user_out or os.path.join(cwd, CANON_BASENAME))

def resolve_data_path(arg: str|None, cwd: str) -> str:
    """
    For watch/serve: accept a file path or a directory.
    If a directory is given, resolve to <dir>/codebase.harvest.json.
    """
    p = os.path.abspath(arg or os.path.join(cwd, CANON_BASENAME))
    return os.path.join(p, CANON_BASENAME) if os.path.isdir(p) else p