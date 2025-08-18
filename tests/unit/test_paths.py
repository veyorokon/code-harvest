"""Tests for path utilities."""
import pytest
import tempfile
import os
from pathlib import Path
from harvest.paths import resolve_reap_out, resolve_data_path


class TestReapOutputResolution:
    def test_explicit_output_path(self):
        # When user specifies --out, use it exactly
        result = resolve_reap_out("custom.json", "/some/target")
        assert result == os.path.abspath("custom.json")
    
    def test_directory_based_naming(self):
        # Should use directory name for output
        with tempfile.TemporaryDirectory() as temp_dir:
            target_dir = Path(temp_dir) / "myproject"
            target_dir.mkdir()
            
            result = resolve_reap_out(None, str(target_dir))
            expected = os.path.abspath("myproject.harvest.json")
            assert result == expected
    
    def test_current_directory_naming(self):
        # When targeting current directory
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.chdir(temp_dir)
                
                result = resolve_reap_out(None, ".")
                dir_name = Path(temp_dir).name
                expected = os.path.abspath(f"{dir_name}.harvest.json")
                assert result == expected
        finally:
            os.chdir(original_cwd)
    
    def test_non_directory_target(self):
        # When target is not a directory, fallback to default
        result = resolve_reap_out(None, "/nonexistent/path")
        expected = os.path.abspath("codebase.harvest.json")
        assert result == expected
    
    def test_none_target_fallback(self):
        # When no target specified
        result = resolve_reap_out(None, None)
        expected = os.path.abspath("codebase.harvest.json")
        assert result == expected


class TestDataPathResolution:
    def test_explicit_file_path(self):
        # When user provides specific file
        result = resolve_data_path("my-harvest.json", "/some/cwd")
        assert result == os.path.abspath("my-harvest.json")
    
    def test_directory_path(self):
        # When user provides directory, append default filename
        with tempfile.TemporaryDirectory() as temp_dir:
            result = resolve_data_path(temp_dir, "/some/cwd")
            expected = os.path.join(temp_dir, "codebase.harvest.json")
            assert result == expected
    
    def test_none_path_default(self):
        # When no path provided, use default in cwd
        result = resolve_data_path(None, "/some/cwd")
        expected = os.path.join("/some/cwd", "codebase.harvest.json")
        assert result == expected
    
    def test_relative_path_resolution(self):
        # Should resolve to absolute paths
        result = resolve_data_path("./relative/path", "/base/dir")
        assert os.path.isabs(result)
        assert "relative/path" in result