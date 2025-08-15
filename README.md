# harvest-code

Harvest codebases into portable JSON + chunks for RAG, tooling, and analysis.

[![PyPI](https://img.shields.io/pypi/v/harvest-code)](https://pypi.org/project/harvest-code/) [![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://python.org) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Quick Start

```bash
pip install harvest-code
harvest reap . -o my-codebase.json
harvest serve my-codebase.json  # Web UI at http://localhost:8787
```

![harvest Web UI](https://raw.githubusercontent.com/veyorokon/code-harvest/main/.github/assets/harvest-web-ui-screenshot.png)

*Interactive web interface with search, filtering, syntax highlighting, and progressive loading*

## Key Features

- 🔍 **Zero-dependency** codebase harvesting from local directories or GitHub URLs
- 📊 **Smart chunking** by functions, classes, exports with content-agnostic IDs
- 🌐 **Interactive Web UI** with search, filtering, syntax highlighting, and deep linking
- 🚀 **Progressive loading** - handles 50k+ files with infinite scroll pagination
- 📝 **Schema v1.2** with stable chunk identifiers for incremental updates
- 🎯 **Intelligent defaults** - automatically skips binaries, caches, build artifacts, and lockfiles
- ⚡ **Fast filtering** - by language, visibility, file patterns, and symbols
- 💾 **Saved views** - bookmark and share specific filtered states

## Use Cases

- **RAG/AI Systems**: Feed structured code context to LLMs with precise chunk boundaries
- **Documentation**: Auto-generate API references from exported symbols and functions  
- **Code Analysis**: Extract dependencies, exports, and architectural patterns
- **Legacy Migration**: Understand large codebases through progressive exploration
- **Code Search**: Find functions, classes, and patterns across entire repositories

## Installation

```bash
pip install harvest-code
```

**Requirements**: Python 3.9+ (no dependencies)

## Core Commands

### Harvest Local Directory

```bash
# Basic harvesting
harvest reap . -o codebase.json
harvest reap /path/to/project -o output.json

# With size limits
harvest reap . --max-files 1000 --max-bytes 512000

# Include everything (override smart defaults)
harvest reap . --no-default-excludes -o full-harvest.json
```

### Harvest from GitHub

```bash
harvest reap https://github.com/user/repo -o repo.json
harvest reap https://github.com/user/repo/tree/main/src -o src-only.json
```

### Query & Filter  

```bash
# Find all public Python functions
harvest query output.json --entity chunks --language python --public true

# Search specific paths with custom fields
harvest query output.json --path-glob "src/**" --fields path,symbol,kind,start_line

# Find exports and components
harvest query output.json --entity files --export-named "MyComponent" 
harvest query output.json --entity chunks --kind export_default --language typescript
```

### Interactive Web Interface

```bash
harvest serve output.json --port 8080
# Browse at http://localhost:8080
```

**Web UI Features:**
- **Search & Filter**: Real-time filtering by language, path, symbols
- **Syntax Highlighting**: Toggle-able code highlighting for 10+ languages  
- **Progressive Loading**: Infinite scroll for large datasets
- **Deep Linking**: Share URLs to specific files and line ranges
- **Saved Views**: Bookmark filtered states for quick access
- **Mobile Responsive**: Works on desktop, tablet, and mobile

## Output Schema

harvest-code produces JSON with three main sections:

```json
{
  "metadata": {
    "schema": "harvest/v1.2",
    "source": {"type": "local", "root": "/path/to/code"},
    "counts": {"total_files": 150, "total_bytes": 524288},
    "created_at": "2025-08-15T12:00:00Z"
  },
  "data": [
    {
      "path": "src/utils.py",
      "language": "python", 
      "size": 1024,
      "exports": null,
      "py_symbols": {"functions": ["helper"], "classes": ["Util"]},
      "content": "def helper():\n    pass\n\nclass Util:\n    pass"
    }
  ],
  "chunks": [
    {
      "id": "abc123...",
      "file_path": "src/utils.py",
      "language": "python",
      "kind": "function",
      "symbol": "helper", 
      "start_line": 1,
      "end_line": 2,
      "public": true
    }
  ]
}
```

## Advanced Usage

### Custom Exclusions

```bash
# Skip additional file types
harvest reap . --skip-ext .log,.tmp --skip-folder cache,temp

# Include only specific languages  
harvest reap . --only-ext .py,.js,.ts
```

### Incremental Updates

```bash
# Reuse unchanged files for faster re-harvesting
harvest reap . --prev previous-harvest.json -o updated.json
```

### Large Codebases

The web UI automatically handles large datasets with:
- **Pagination**: Loads 50 items at a time by default
- **Infinite Scroll**: Seamlessly loads more results
- **Cursor-based Navigation**: Efficient browsing of 10k+ items
- **Smart Filtering**: Client-side filtering for responsive UX

## Default Exclusions

harvest-code intelligently skips common non-source files:

**File Extensions**: `.log`, `.tmp`, `.db`, `.sqlite`, `.mp4`, `.jpg`, `.png`, `.zip`, `.exe`, `.pyc`, `.min.js`, `.woff`, `.pb`, `.tflite`, etc.

**Directories**: `node_modules`, `.git`, `dist`, `build`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.vscode`, `.idea`, `.next`, `Pods`, `DerivedData`, etc.

**Lockfiles**: `yarn.lock`, `package-lock.json`, `poetry.lock`, `Cargo.lock`, `go.sum`, etc.

Use `--no-default-excludes` to include everything.

## Language Support

**Chunking & Symbol Extraction**:
- **Python**: Functions, classes, exports via AST parsing
- **JavaScript/TypeScript**: Functions, classes, React components, ES6/CommonJS exports
- **JSON/YAML/TOML**: Single file chunks with metadata

**Syntax Highlighting**: Python, JavaScript, TypeScript, JSON, YAML, TOML, Markdown, Shell, Go, Rust

## API Integration

The web server exposes REST endpoints for programmatic access:

```bash
curl http://localhost:8787/api/search?entity=chunks&language=python&limit=10
curl http://localhost:8787/api/meta  # Get harvest metadata
```

## Examples

### RAG Pipeline Integration

```python
import json

# Load harvest data
with open('codebase.json') as f:
    harvest = json.load(f)

# Extract public API functions for LLM context
api_functions = [
    chunk for chunk in harvest['chunks'] 
    if chunk['public'] and chunk['kind'] in ['function', 'export_named']
]
```

### Documentation Generation

```bash
# Extract all exported React components
harvest query react-app.json --entity chunks --kind export_default --language typescript --fields symbol,file_path > components.txt
```

### Migration Analysis

```bash
# Find all Python classes for refactoring
harvest query legacy-app.json --entity chunks --kind class --language python --min-lines 10
```

## Contributing

We welcome contributions! Please see our [Contributing Guidelines](CONTRIBUTING.md) for details.

**Development Setup**:
```bash
git clone https://github.com/veyorokon/code-harvest.git
cd code-harvest  
pip install -e .
harvest reap . -o self-harvest.json  # Harvest itself!
```

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Links

- **PyPI**: https://pypi.org/project/harvest-code/
- **GitHub**: https://github.com/veyorokon/code-harvest
- **Issues**: https://github.com/veyorokon/code-harvest/issues
- **Documentation**: https://github.com/veyorokon/code-harvest/wiki