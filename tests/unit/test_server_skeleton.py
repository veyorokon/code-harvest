"""Tests for server skeleton endpoint functionality."""
import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from urllib.parse import urlparse, parse_qs
from harvest.server import make_handler, ServeState


class TestSkeletonEndpoint:
    def setup_method(self):
        # Create test harvest data
        self.test_payload = {
            "metadata": {"schema": "harvest/v1.2"},
            "data": [
                {
                    "path": "main.py",
                    "language": "python",
                    "content": "def main():\n    print('hello')\n    return True\n\nclass Test:\n    def __init__(self):\n        self.name = 'test'"
                },
                {
                    "path": "utils.js",
                    "language": "javascript", 
                    "content": "function helper() {\n    return 42;\n}\n\nexport default helper;"
                }
            ]
        }
        
        self.state = ServeState(self.test_payload)
        self.handler_class = make_handler(self.state)
    
    def create_mock_handler(self, path):
        """Create a properly mocked handler instance"""
        handler = self.handler_class.__new__(self.handler_class)
        handler.path = path
        handler.headers = {}
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = Mock()
        handler.log_message = Mock()  # Suppress logs
        return handler
    
    def test_regular_file_endpoint(self):
        # Test normal file content retrieval
        handler = self.create_mock_handler("/api/file?path=main.py")
        
        # Mock the response methods
        response_data = None
        def mock_send_json(data, **kwargs):
            nonlocal response_data
            response_data = data
        
        handler.send_json = mock_send_json
        handler.do_GET()
        
        assert response_data is not None
        assert response_data["path"] == "main.py"
        assert "def main():" in response_data["text"]
        assert "print('hello')" in response_data["text"]  # Full content
        assert response_data["start"] == 1
    
    def test_skeleton_file_endpoint(self):
        # Test skeleton content retrieval
        handler = self.create_mock_handler("/api/file?path=main.py&skeleton=1")
        
        response_data = None
        def mock_send_json(data, **kwargs):
            nonlocal response_data
            response_data = data
        
        handler.send_json = mock_send_json
        handler.do_GET()
        
        assert response_data is not None
        assert response_data["path"] == "main.py"
        # Should contain signatures but not implementation
        assert "def main():" in response_data["text"]
        assert "class Test:" in response_data["text"]
        assert "print('hello')" not in response_data["text"]  # Implementation stripped
        assert "return True" not in response_data["text"]
    
    def test_skeleton_javascript_file(self):
        # Test skeleton for JavaScript
        handler = self.create_mock_handler("/api/file?path=utils.js&skeleton=1")
        
        response_data = None
        def mock_send_json(data, **kwargs):
            nonlocal response_data
            response_data = data
        
        handler.send_json = mock_send_json
        handler.do_GET()
        
        assert response_data is not None
        assert response_data["path"] == "utils.js"
        # Should extract function signature
        text = response_data["text"]
        assert "function helper" in text or "helper(…)" in text
        assert "export default helper" in text or "export default" in text
    
    def test_skeleton_parameter_variations(self):
        # Test different ways to specify skeleton parameter
        test_cases = [
            "skeleton=1",
            "skeleton=true", 
            "skeleton=yes"
        ]
        
        for param in test_cases:
            handler = self.create_mock_handler(f"/api/file?path=main.py&{param}")
            
            response_data = None
            def mock_send_json(data, **kwargs):
                nonlocal response_data
                response_data = data
            
            handler.send_json = mock_send_json
            handler.do_GET()
            
            # Should all trigger skeleton rendering
            assert "print('hello')" not in response_data["text"]
    
    def test_line_range_with_skeleton(self):
        # Test skeleton rendering with line range
        handler = self.create_mock_handler("/api/file?path=main.py&start=1&end=3&skeleton=1")
        
        response_data = None
        def mock_send_json(data, **kwargs):
            nonlocal response_data
            response_data = data
        
        handler.send_json = mock_send_json
        handler.do_GET()
        
        assert response_data is not None
        assert response_data["start"] == 1
        assert response_data["end"] == 3
        # Should still apply skeleton rendering to the selected range
        assert "def main():" in response_data["text"]
    
    def test_file_not_found(self):
        # Test skeleton request for non-existent file
        handler = self.create_mock_handler("/api/file?path=nonexistent.py&skeleton=1")
        
        response_data = None
        def mock_send_json(data, **kwargs):
            nonlocal response_data
            response_data = data
        
        handler.send_json = mock_send_json
        handler.do_GET()
        
        assert response_data is not None
        assert "error" in response_data
        assert "not found" in response_data["error"].lower()
    
    def test_missing_path_parameter(self):
        # Test skeleton request without path parameter
        handler = self.create_mock_handler("/api/file?skeleton=1")
        
        # Mock response sending
        response_code = None
        def mock_send_response(code):
            nonlocal response_code
            response_code = code
        
        def mock_end_headers():
            pass
        
        handler.send_response = mock_send_response
        handler.end_headers = mock_end_headers
        handler.do_GET()
        
        assert response_code == 400  # Bad Request