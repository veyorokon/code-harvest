"""Integration test for watch+serve mode to validate auto-refresh behavior"""
import pytest
import tempfile
import shutil
import threading
import time
import subprocess
import sys
import json
import requests
from pathlib import Path

@pytest.mark.skipif(shutil.which("harvest") is None, reason="harvest CLI not available")
def test_watch_serve_auto_refresh():
    """Test that watch+serve mode updates API responses when files change"""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        
        # Create initial test file
        test_file = tmppath / "test.py"
        test_file.write_text('print("initial version")')
        
        # Start harvest serve with watch in background
        server_process = subprocess.Popen([
            sys.executable, "-m", "harvest.cli", "serve", str(tmppath), 
            "--watch", "--port", "8789"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        try:
            # Wait for server to start
            time.sleep(3)
            
            # Check initial state
            response = requests.get("http://localhost:8789/api/meta", timeout=5)
            assert response.status_code == 200
            initial_meta = response.json()
            initial_version = initial_meta["version"]
            
            # Verify initial file content
            file_response = requests.get("http://localhost:8789/api/file?path=test.py", timeout=5)
            assert file_response.status_code == 200
            initial_content = file_response.json()["text"]
            assert "initial version" in initial_content
            
            # Update the file
            test_file.write_text('print("updated version")')
            
            # Wait for watch to detect change and update
            time.sleep(5)  # debounce + processing time
            
            # Check that version incremented
            response = requests.get("http://localhost:8789/api/meta", timeout=5)
            assert response.status_code == 200
            updated_meta = response.json()
            updated_version = updated_meta["version"]
            
            assert updated_version > initial_version, f"Version should increment: {initial_version} -> {updated_version}"
            
            # Verify file content was updated
            file_response = requests.get("http://localhost:8789/api/file?path=test.py", timeout=5)
            assert file_response.status_code == 200
            updated_content = file_response.json()["text"]
            assert "updated version" in updated_content
            assert "initial version" not in updated_content
            
            # Test ETag changes
            initial_etag = initial_meta.get("etag")
            updated_etag = updated_meta.get("etag")
            if initial_etag and updated_etag:
                assert initial_etag != updated_etag, "ETag should change when content changes"
                
        finally:
            # Clean up server process
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_process.kill()