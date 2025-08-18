"""Tests for core harvesting functionality."""
import pytest
import tempfile
import json
from pathlib import Path
from harvest.core import HarvestEngine, detect_language, extract_js_ts_exports, extract_py_symbols


class TestLanguageDetection:
    def test_python_files(self):
        assert detect_language("test.py") == "python"
        assert detect_language("module.pyi") is None  # Not in LANG_MAP
    
    def test_javascript_files(self):
        assert detect_language("app.js") == "javascript"
        assert detect_language("Component.jsx") == "javascriptreact"
    
    def test_typescript_files(self):
        assert detect_language("utils.ts") == "typescript"
        assert detect_language("Button.tsx") == "typescriptreact"
    
    def test_config_files(self):
        assert detect_language("package.json") == "json"
        assert detect_language("config.yaml") == "yaml"
        assert detect_language("pyproject.toml") == "toml"
    
    def test_unknown_extension(self):
        assert detect_language("file.xyz") is None
        assert detect_language("README") is None


class TestJavaScriptExportExtraction:
    def test_default_export_function(self):
        src = "export default function MyComponent() { return null; }"
        result = extract_js_ts_exports(src, "MyComponent")
        assert result["default"] == "MyComponent"
    
    def test_default_export_variable(self):
        src = "const Button = () => {}; export default Button;"
        result = extract_js_ts_exports(src, "Button")
        assert result["default"] == "Button"
    
    def test_named_exports(self):
        src = """
export const API_URL = 'https://api.com';
export function fetchUser(id) { return fetch('/users/' + id); }
export class UserService {}
"""
        result = extract_js_ts_exports(src, "utils")
        named = result["named"]
        assert "API_URL" in named
        assert "fetchUser" in named
        assert "UserService" in named
    
    def test_export_object(self):
        src = "export { Component, Button as UIButton };"
        result = extract_js_ts_exports(src, "components")
        named = result["named"]
        assert "Component" in named
        assert "UIButton" in named
    
    def test_commonjs_exports(self):
        src = """
module.exports = {
  helper: function() {},
  CONSTANT: 42
};
exports.utils = {};
"""
        result = extract_js_ts_exports(src, "module")
        named = result["named"]
        assert "helper" in named
        assert "CONSTANT" in named
        assert "utils" in named


class TestPythonSymbolExtraction:
    def test_function_extraction(self):
        src = """
def public_function():
    pass

def _private_function():
    pass

async def async_function():
    pass
"""
        result = extract_py_symbols(src)
        named = result["named"]
        assert "public_function" in named
        assert "_private_function" in named
        assert "async_function" in named
    
    def test_class_extraction(self):
        src = """
class PublicClass:
    pass

class _PrivateClass:
    pass
"""
        result = extract_py_symbols(src)
        named = result["named"]
        assert "PublicClass" in named
        assert "_PrivateClass" in named
    
    def test_syntax_error_handling(self):
        src = "def broken_syntax("  # Invalid Python
        result = extract_py_symbols(src)
        assert result == {"named": []}


class TestHarvestEngineFiltering:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        
        # Create test files
        (self.temp_path / "main.py").write_text("def main(): pass")
        (self.temp_path / "utils.js").write_text("function helper() {}")
        (self.temp_path / "styles.css").write_text("body { margin: 0; }")
        (self.temp_path / "data.json").write_text('{"key": "value"}')
        (self.temp_path / "README.md").write_text("# Project")
        (self.temp_path / ".hidden").write_text("secret")
        (self.temp_path / "test.log").write_text("log data")
    
    def test_default_excludes(self):
        engine = HarvestEngine(apply_default_excludes=True)
        result = engine.harvest_local(str(self.temp_path))
        
        paths = {f["path"] for f in result["data"]}
        assert "main.py" in paths
        assert "utils.js" in paths
        assert "README.md" in paths
        assert ".hidden" not in paths  # Hidden file excluded
        assert "test.log" not in paths  # Log file excluded
    
    def test_only_ext_filter(self):
        engine = HarvestEngine(only_ext={".py", ".js"})
        result = engine.harvest_local(str(self.temp_path))
        
        paths = {f["path"] for f in result["data"]}
        assert "main.py" in paths
        assert "utils.js" in paths
        assert "styles.css" not in paths
        assert "data.json" not in paths
        assert "README.md" not in paths
    
    def test_skip_ext_override(self):
        engine = HarvestEngine(skip_ext_override={".js", ".css"})
        result = engine.harvest_local(str(self.temp_path))
        
        paths = {f["path"] for f in result["data"]}
        assert "main.py" in paths
        assert "README.md" in paths
        assert "utils.js" not in paths  # Skipped by override
        assert "styles.css" not in paths  # Skipped by override
    
    def test_no_default_excludes(self):
        engine = HarvestEngine(apply_default_excludes=False)
        result = engine.harvest_local(str(self.temp_path))
        
        paths = {f["path"] for f in result["data"]}
        assert ".hidden" in paths  # Hidden file included
        assert "test.log" in paths  # Log file included
    
    def test_file_count_limit(self):
        engine = HarvestEngine(max_files=2)
        result = engine.harvest_local(str(self.temp_path))
        
        # Should only process first 2 files (exact count depends on file system order)
        assert len(result["data"]) <= 2
    
    def test_path_only_files(self):
        # Create an image file that should be path-only
        (self.temp_path / "image.jpg").write_bytes(b"fake image data")
        
        engine = HarvestEngine()
        result = engine.harvest_local(str(self.temp_path))
        
        # Find the image file
        image_file = next((f for f in result["data"] if f["path"] == "image.jpg"), None)
        assert image_file is not None
        assert image_file["content"] == ""  # No content for path-only files
        assert image_file["truncated_reason"] == "path_only"


class TestHarvestEngineOutput:
    def test_metadata_structure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "test.py").write_text("def test(): pass")
            
            engine = HarvestEngine()
            result = engine.harvest_local(temp_dir)
            
            metadata = result["metadata"]
            assert metadata["schema"] == "harvest/v1.2"
            assert metadata["source"]["type"] == "local"
            assert metadata["source"]["root"] == temp_dir
            assert "created_at" in metadata
            assert "counts" in metadata
            assert metadata["counts"]["total_files"] >= 1
    
    def test_chunks_generation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "test.py").write_text("""
def public_func():
    pass

def _private_func():
    pass

class TestClass:
    def method(self):
        pass
""")
            
            engine = HarvestEngine()
            result = engine.harvest_local(temp_dir)
            
            chunks = result["chunks"]
            assert len(chunks) >= 3  # 2 functions + 1 class + 1 method
            
            # Check chunk structure
            chunk = chunks[0]
            assert "id" in chunk
            assert "file_path" in chunk
            assert "language" in chunk
            assert "kind" in chunk
            assert "symbol" in chunk
            assert "start_line" in chunk
            assert "end_line" in chunk
            assert "public" in chunk
            assert "hash" in chunk