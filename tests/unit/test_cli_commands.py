"""Tests for CLI command functionality."""
import pytest
import tempfile
import json
import io
import sys
from pathlib import Path
from unittest.mock import patch
from harvest.cli import cmd_reap, cmd_winnow, cmd_query


class MockArgs:
    """Mock argparse.Namespace for testing"""
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class TestReapCommand:
    def test_basic_harvest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test files
            (Path(temp_dir) / "main.py").write_text("def main(): pass")
            (Path(temp_dir) / "utils.js").write_text("function helper() {}")
            
            args = MockArgs(
                target=temp_dir,
                out=None,  # Will use default naming
                max_bytes=524288,
                max_files=5000,
                format="json",
                mirror_out=None,
                no_default_excludes=False,
                include=["metadata", "data", "chunks"],
                exclude=None,
                only_ext=None,
                skip_ext=None
            )
            
            cmd_reap(args)
            
            # Check output file was created
            expected_output = Path(temp_dir).name + ".harvest.json"
            assert Path(expected_output).exists()
            
            # Verify content structure
            with open(expected_output) as f:
                result = json.load(f)
            
            assert "metadata" in result
            assert "data" in result
            assert "chunks" in result
            assert len(result["data"]) >= 2  # Should have both files
            
            # Cleanup
            Path(expected_output).unlink()
    
    def test_extension_filtering(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test files
            (Path(temp_dir) / "main.py").write_text("def main(): pass")
            (Path(temp_dir) / "utils.js").write_text("function helper() {}")
            (Path(temp_dir) / "styles.css").write_text("body { margin: 0; }")
            
            args = MockArgs(
                target=temp_dir,
                out=None,
                max_bytes=524288,
                max_files=5000,
                format="json",
                mirror_out=None,
                no_default_excludes=False,
                include=["data"],
                exclude=None,
                only_ext=".py",  # Only Python files
                skip_ext=None
            )
            
            cmd_reap(args)
            
            expected_output = Path(temp_dir).name + ".harvest.json"
            with open(expected_output) as f:
                result = json.load(f)
            
            paths = {f["path"] for f in result["data"]}
            assert "main.py" in paths
            assert "utils.js" not in paths
            assert "styles.css" not in paths
            
            # Cleanup
            Path(expected_output).unlink()
    
    def test_data_only_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "test.py").write_text("print('hello')")
            
            args = MockArgs(
                target=temp_dir,
                out=None,
                max_bytes=524288,
                max_files=5000,
                format="json",
                mirror_out=None,
                no_default_excludes=False,
                include=["data"],  # Data only
                exclude=None,
                only_ext=None,
                skip_ext=None
            )
            
            cmd_reap(args)
            
            expected_output = Path(temp_dir).name + ".harvest.json"
            with open(expected_output) as f:
                result = json.load(f)
            
            assert "data" in result
            assert "metadata" not in result
            assert "chunks" not in result
            
            # Cleanup
            Path(expected_output).unlink()


class TestWinnowCommand:
    def setup_method(self):
        # Create a test harvest file
        self.temp_dir = tempfile.mkdtemp()
        self.harvest_file = Path(self.temp_dir) / "test.harvest.json"
        
        test_data = {
            "data": [
                {
                    "path": "main.py",
                    "language": "python",
                    "content": "def main():\n    print('hello')\n\nclass Test:\n    pass"
                },
                {
                    "path": "utils.js", 
                    "language": "javascript",
                    "content": "function helper() {\n    return true;\n}"
                }
            ]
        }
        
        with open(self.harvest_file, 'w') as f:
            json.dump(test_data, f)
    
    def test_skeleton_extraction_default_output(self):
        args = MockArgs(
            json=str(self.harvest_file),
            skeleton=True,
            language=None,
            out=None,  # Should use default naming
            format="jsonl"
        )
        
        cmd_winnow(args)
        
        # Check default output file
        expected_output = self.temp_dir + "/test.skeleton.harvest.jsonl"
        assert Path(expected_output).exists()
        
        # Verify content
        with open(expected_output) as f:
            lines = f.readlines()
        
        assert len(lines) == 2  # Two files
        
        # Parse first line (Python file)
        python_data = json.loads(lines[0])
        assert python_data["path"] == "main.py"
        assert python_data["language"] == "python"
        assert "def main():" in python_data["text"]
        assert "class Test:" in python_data["text"]
        assert "print('hello')" not in python_data["text"]  # Body removed
    
    def test_language_filtering(self):
        args = MockArgs(
            json=str(self.harvest_file),
            skeleton=True,
            language="python",  # Only Python
            out=None,
            format="jsonl"
        )
        
        cmd_winnow(args)
        
        expected_output = self.temp_dir + "/test.skeleton.harvest.jsonl"
        with open(expected_output) as f:
            lines = f.readlines()
        
        assert len(lines) == 1  # Only Python file
        
        python_data = json.loads(lines[0])
        assert python_data["language"] == "python"
    
    def test_markdown_format(self):
        args = MockArgs(
            json=str(self.harvest_file),
            skeleton=True,
            language=None,
            out=None,
            format="md"
        )
        
        cmd_winnow(args)
        
        expected_output = self.temp_dir + "/test.skeleton.harvest.md"
        assert Path(expected_output).exists()
        
        with open(expected_output) as f:
            content = f.read()
        
        assert "# Code Skeleton" in content
        assert "## Python" in content
        assert "## Javascript" in content
        assert "```python" in content
        assert "def main():" in content
    
    def test_stdout_output(self):
        args = MockArgs(
            json=str(self.harvest_file),
            skeleton=True,
            language="python",
            out="-",  # stdout
            format="jsonl"
        )
        
        # Capture stdout
        captured_output = io.StringIO()
        with patch('sys.stdout', captured_output):
            cmd_winnow(args)
        
        output = captured_output.getvalue()
        assert output.strip()  # Should have output
        
        # Should be valid JSON
        data = json.loads(output.strip())
        assert data["language"] == "python"


class TestQueryCommand:
    def setup_method(self):
        # Create test harvest with chunks
        self.temp_dir = tempfile.mkdtemp()
        self.harvest_file = Path(self.temp_dir) / "test.harvest.json"
        
        test_data = {
            "data": [
                {
                    "path": "main.py",
                    "language": "python",
                    "exports": None
                }
            ],
            "chunks": [
                {
                    "file_path": "main.py",
                    "language": "python",
                    "kind": "function",
                    "symbol": "main",
                    "public": True,
                    "start_line": 1,
                    "end_line": 3
                },
                {
                    "file_path": "main.py", 
                    "language": "python",
                    "kind": "function",
                    "symbol": "_helper",
                    "public": False,
                    "start_line": 5,
                    "end_line": 7
                }
            ]
        }
        
        with open(self.harvest_file, 'w') as f:
            json.dump(test_data, f)
    
    def test_query_chunks_by_language(self):
        args = MockArgs(
            json=str(self.harvest_file),
            entity="chunks",
            language="python",
            kind=None,
            path_glob=None,
            path_regex=None,
            symbol_regex=None,
            public=None,
            min_lines=None,
            max_lines=None,
            export_named=None,
            has_default_export=False,
            fields=None
        )
        
        # Capture stdout
        captured_output = io.StringIO()
        with patch('sys.stdout', captured_output):
            cmd_query(args)
        
        output_lines = captured_output.getvalue().strip().split('\n')
        assert len(output_lines) == 2  # Both chunks match
        
        # Parse and verify
        chunk1 = json.loads(output_lines[0])
        assert chunk1["language"] == "python"
    
    def test_query_public_only(self):
        args = MockArgs(
            json=str(self.harvest_file),
            entity="chunks",
            language=None,
            kind=None,
            path_glob=None,
            path_regex=None,
            symbol_regex=None,
            public="true",  # Only public chunks
            min_lines=None,
            max_lines=None,
            export_named=None,
            has_default_export=False,
            fields=None
        )
        
        captured_output = io.StringIO()
        with patch('sys.stdout', captured_output):
            cmd_query(args)
        
        output_lines = captured_output.getvalue().strip().split('\n')
        assert len(output_lines) == 1  # Only public function
        
        chunk = json.loads(output_lines[0])
        assert chunk["symbol"] == "main"
        assert chunk["public"] is True
    
    def test_query_with_fields(self):
        args = MockArgs(
            json=str(self.harvest_file),
            entity="chunks",
            language=None,
            kind=None,
            path_glob=None,
            path_regex=None,
            symbol_regex=None,
            public=None,
            min_lines=None,
            max_lines=None,
            export_named=None,
            has_default_export=False,
            fields="symbol,kind,public"
        )
        
        captured_output = io.StringIO()
        with patch('sys.stdout', captured_output):
            cmd_query(args)
        
        output_lines = captured_output.getvalue().strip().split('\n')
        assert len(output_lines) == 2
        
        # Should be tab-separated values
        fields = output_lines[0].split('\t')
        assert len(fields) == 3  # symbol, kind, public