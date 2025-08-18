import os

def etag_for(path: str) -> str:
    st = os.stat(path)
    return f'W/"{st.st_mtime_ns}-{st.st_size}"'

def write_no_store_headers(handler, *, etag: str|None = None, ctype: str = "application/json"):
    handler.send_header("Content-Type", ctype)
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
    handler.send_header("Pragma", "no-cache")
    handler.send_header("Expires", "0")
    if etag:
        handler.send_header("ETag", etag)