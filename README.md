# harvest-code

Extract codebases into portable JSON for RAG, tooling, and analysis.

[![PyPI](https://img.shields.io/pypi/v/harvest-code)](https://pypi.org/project/harvest-code/) [![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://python.org) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Quick Start

```bash
pip install harvest-code
harvest serve  # Watch + serve current directory at http://localhost:8787
```

![harvest Web UI](https://raw.githubusercontent.com/veyorokon/code-harvest/master/.github/assets/harvest-web-ui-screenshot.png)

## Features

- 🔍 **Zero dependencies** - Pure Python, no external packages required
- 📊 **Smart chunking** - Extracts functions, classes, exports with stable IDs
- 🌐 **Interactive UI** - Web interface with search, filtering, and syntax highlighting
- 🎯 **Intelligent filtering** - Automatically skips build artifacts, binaries, and test files
- ⚡ **Live updates** - Auto-refreshes when files change (watch mode)
- 🚀 **Scales** - Handles 50k+ files with progressive loading

## Commands

### `harvest reap` - Extract codebase to JSON

```bash
# Basic usage - output named after directory
harvest reap .                    # → ./current-dir-name.harvest.json
harvest reap /path/to/project     # → ./project.harvest.json

# Custom output
harvest reap . -o analysis.json

# Control what's included
harvest reap . --include metadata       # File inventory only
harvest reap . --include data          # File contents only  
harvest reap . --exclude chunks        # Skip code parsing
harvest reap . --format jsonl          # Line-delimited JSON

# Override filters
harvest reap . --no-default-excludes   # Include hidden files, tests, etc.
```

### `harvest serve` - Interactive web UI

```bash
# Watch + serve (default)
harvest serve                    # Current directory on port 8787
harvest serve /path/to/project   # Specific directory
harvest serve --port 8080        # Custom port

# Control options
harvest serve --no-watch         # Disable auto-refresh
harvest serve --only-ext py,ts   # Watch specific file types
```

**Web UI Features:**
- Real-time search and filtering
- Syntax highlighting with toggle
- Auto-refresh on file changes
- Infinite scroll for large codebases
- Deep linking to specific files/lines

### `harvest query` - Search harvest data

```bash
# Find specific code elements
harvest query data.json --entity chunks --language python --public true
harvest query data.json --entity files --export-named "MyComponent"
harvest query data.json --path-glob "src/**" --fields path,symbol,kind
```

### `harvest watch` - Monitor directory changes

```bash
# Continuous harvesting
harvest watch .                        # → ./<dirname>.harvest.json
harvest watch /path/to/src -o out.json # Custom output
harvest watch . --only-ext py,js,ts    # Specific extensions
```

### `harvest sow` - Generate artifacts

```bash
# Create React barrel exports
harvest sow data.json --react src/index.ts
```

## Output Structure

harvest generates JSON with three sections:

```json
{
  "metadata": {
    "schema": "harvest/v1.2",
    "source": {"type": "local", "root": "/path/to/code"},
    "counts": {"total_files": 150, "total_bytes": 524288}
  },
  "data": [
    {
      "path": "src/utils.py",
      "language": "python",
      "content": "def helper():\n    pass",
      "exports": null,
      "py_symbols": {"functions": ["helper"]}
    }
  ],
  "chunks": [
    {
      "id": "abc123...",
      "file_path": "src/utils.py",
      "kind": "function",
      "symbol": "helper",
      "start_line": 1,
      "end_line": 2,
      "public": true
    }
  ]
}
```

### Output Sections

- **metadata** - File inventory, counts, timestamps
- **data** - File contents and language metadata
- **chunks** - Parsed symbols (functions, classes, exports)

Control output with `--include` and `--exclude`:

```bash
harvest reap . --include metadata       # Inventory only (fast)
harvest reap . --exclude chunks         # Skip parsing (smaller)
harvest reap . --include chunks         # Symbols only (for analysis)
```

## File Handling

### Smart Filtering

harvest uses a three-tier filtering system:

**Completely Skipped:**
- Hidden files and directories (`.git/`, `.env`)
- Test directories (`tests/`, `__tests__/`)
- Build artifacts (`dist/`, `build/`, `node_modules/`)
- Binaries and media (`.exe`, `.mp3`, `.db`)
- Logs and temp files (`.log`, `.tmp`)

**Path-Only (no content):**
- Images (`.jpg`, `.png`, `.svg`)
- Fonts (`.ttf`, `.woff`)
- Documents (`.pdf`, `.doc`)

**Fully Processed:**
- Source code (`.py`, `.js`, `.ts`, etc.)
- Config files (`.json`, `.yaml`, `.toml`)
- Documentation (`.md`, `.txt`)

Override with `--no-default-excludes` to include everything.

## Language Support

**Full parsing** (chunks + symbols):
- Python - Functions, classes via AST
- JavaScript/TypeScript - Functions, classes, React components, ES6/CommonJS exports
- JSON/YAML/TOML - Single file chunks

**Syntax highlighting** in web UI:
Python, JavaScript, TypeScript, JSON, YAML, TOML, Markdown, Shell, Go, Rust

## API Endpoints

The web server exposes REST APIs:

```bash
# Search chunks
curl http://localhost:8787/api/search?entity=chunks&language=python

# Get metadata
curl http://localhost:8787/api/meta

# Download full harvest
curl http://localhost:8787/api/harvest
```

## Use Cases

### RAG/LLM Context

```python
import json

with open('project.harvest.json') as f:
    harvest = json.load(f)

# Extract public functions for context
api_functions = [
    chunk for chunk in harvest['chunks'] 
    if chunk['public'] and chunk['kind'] == 'function'
]
```

### Code Analysis

```bash
# Find all React components
harvest query app.json --entity chunks --kind export_default --language typescript

# Find large classes
harvest query app.json --entity chunks --kind class --min-lines 100
```

### Documentation Generation

```bash
# Extract all exports
harvest query app.json --entity files --has-default-export --fields path,exports
```

## File Naming

- Output files use pattern: `<directory-name>.harvest.json`
- Created in current working directory (where command is run)
- Use `-o` flag for custom names/paths
- All `*.harvest.json` files are automatically ignored to prevent recursion

## Development

```bash
git clone https://github.com/veyorokon/code-harvest.git
cd code-harvest
pip install -e .
harvest reap . -o self.harvest.json
```

## Links

- [PyPI Package](https://pypi.org/project/harvest-code/)
- [GitHub Repository](https://github.com/veyorokon/code-harvest)
- [Issue Tracker](https://github.com/veyorokon/code-harvest/issues)

## License

MIT - see [LICENSE](LICENSE) file