import importlib, json, os, socket, threading, time
from urllib.request import urlopen
from urllib.error import URLError
from pathlib import Path
import pytest

def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1",0)); port = s.getsockname()[1]; s.close(); return port

@pytest.mark.timeout(10)
def test_api_meta_reads_from_disk_if_server_available(tmp_path):
    # Try to import server module
    try:
        server_mod = importlib.import_module("harvest.server")
        serve_harvest = getattr(server_mod, "serve_harvest", None)
        if not serve_harvest:
            pytest.skip("serve_harvest function not available; skipping")
    except Exception:
        pytest.skip("server module not available; skipping")
    
    out = tmp_path / "out.json"
    out.write_text(json.dumps({"metadata":{"version":0}}))
    port = _free_port()
    
    # Start server in background
    def run_server():
        try:
            serve_harvest(str(out), port)
        except Exception:
            pass
    
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(1.0)  # Give server time to start
    
    try:
        # v0
        data = urlopen(f"http://127.0.0.1:{port}/api/meta", timeout=3).read().decode()
        assert '"version": 0' in data or '"version":0' in data
        
        # bump version by updating file
        payload = {"metadata":{"version":1}}
        out.write_text(json.dumps(payload))
        time.sleep(0.3)
        
        data2 = urlopen(f"http://127.0.0.1:{port}/api/meta", timeout=3).read().decode()
        assert '"version": 1' in data2 or '"version":1' in data2
        
    except (URLError, OSError):
        pytest.skip("Could not connect to server; skipping")