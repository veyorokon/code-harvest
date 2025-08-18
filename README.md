# harvest-code

Harvest codebases into portable JSON + chunks for RAG, tooling, and analysis.

[![PyPI](https://img.shields.io/pypi/v/harvest-code)](https://pypi.org/project/harvest-code/) [![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://python.org) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Quick Start

```bash
pip install harvest-code
harvest serve  # Watches current dir, auto-creates harvest, serves at http://localhost:8787
```

![harvest Web UI](https://raw.githubusercontent.com/veyorokon/code-harvest/master/.github/assets/harvest-web-ui-screenshot.png)

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

## Harvest file naming & location

- **Canonical extension:** `.harvest.json`
- **Default location:** `./codebase.harvest.json` (in current directory)
- The harvester and watcher **automatically ignore** any `*.harvest.json` files to prevent recursive harvesting
- Legacy filenames (`.hvst.json`, `.har.json`, `.harvest-code.json`) are still supported but the canonical name is recommended

**Tip:** choose whether to commit the index:
```bash
# .gitignore (optional - exclude harvest files from git)
.harvest/

# OR commit them for reproducible runs
git add .harvest/codebase.harvest.json
```

## Core Commands

### Harvest Local Directory

```bash
# Basic harvesting
harvest reap .  # Creates ./codebase.harvest.json
harvest reap /path/to/project  # Creates /path/to/project/codebase.harvest.json

# Custom output path
harvest reap . -o my-custom-harvest.json

# Control what's included
harvest reap . --include data          # Only file contents, no chunks
harvest reap . --include metadata data  # Metadata + data, no chunks  
harvest reap . --exclude chunks        # Everything except chunks
harvest reap . --include chunks         # Only chunks (for analysis)

# With size limits
harvest reap . --max-files 1000 --max-bytes 512000

# Include everything (override smart defaults)
harvest reap . --no-default-excludes -o full-harvest.json
```

### Harvest from GitHub

```bash
harvest reap https://github.com/user/repo -o repo.harvest.json
harvest reap https://github.com/user/repo/tree/main/src -o src-only.harvest.json
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
harvest serve                    # Watch + serve current directory (default)
harvest serve /path/to/project    # Watch + serve specific directory
harvest serve --no-watch          # Serve without watching for changes
harvest serve --port 8080         # Use custom port
```

**Web UI Features:**
- **Search & Filter**: Real-time filtering by language, path, symbols
- **Syntax Highlighting**: Code highlighting enabled by default with dropdown toggle (Highlight/Plain)
- **Auto-refresh**: Seamless updates when files change in watch mode
- **Progressive Loading**: Infinite scroll for large datasets
- **Deep Linking**: Share URLs to specific files and line ranges
- **Saved Views**: Bookmark filtered states for quick access
- **Mobile Responsive**: Works on desktop, tablet, and mobile

### Live Updates (auto-refresh, zero deps)

`harvest serve` now includes watching by default - no need for separate terminals!

```bash
# Single command for watch + serve (recommended)
harvest serve

# Or run them separately if needed
harvest watch .                   # Terminal 1: Watch only
harvest serve --no-watch          # Terminal 2: Serve only
```

The UI polls `/api/meta` every 3 seconds and automatically refreshes when files change:
- Updates the file list and metadata instantly
- Refreshes the content preview without manual clicking
- Maintains your scroll position and selection
- Shows progress in browser console (`[harvest]` logs) for debugging

All API endpoints send `Cache-Control: no-store` headers to prevent stale data, and the UI includes version parameters for cache busting.

**New endpoint:**
```
GET /api/harvest                # returns the current JSON, uncached, with ETag
```

**Watch Flags:**
- `--debounce-ms 800` - Coalesce bursts of file events (milliseconds)
- `--poll 1.0` - Filesystem snapshot cadence (seconds)  
- `--only-ext py,ts,js` - Include only specific extensions
- `--skip-ext log,tmp` - Exclude specific extensions

The watcher uses portable polling that works on all platforms and performs incremental re-harvesting when files change.

## CLI Reference

### harvest reap - Extract codebase data
```bash
harvest reap [OPTIONS] <directory_or_url>

# Basic usage
harvest reap .                           # Current directory → ./codebase.harvest.json
harvest reap /path/to/project            # Specific directory
harvest reap https://github.com/user/repo  # GitHub repository

# Output control
harvest reap . --include metadata        # File inventory only
harvest reap . --include data           # File contents only
harvest reap . --include chunks         # Parsed symbols only
harvest reap . --exclude chunks         # Files without parsing
harvest reap . --format jsonl           # Line-delimited JSON

# Size limits
harvest reap . --max-files 1000 --max-bytes 512000

# Advanced
harvest reap . --no-default-excludes    # Include hidden files, tests, etc.
harvest reap . --mirror-out backup.json # Write second copy
```

### harvest serve - Interactive web UI (default: watch + serve)
```bash
harvest serve [OPTIONS] [directory_or_file]

# Basic usage
harvest serve                    # Watch current dir, serve at :8787
harvest serve /path/to/project   # Watch specific directory
harvest serve --port 8080        # Custom port

# Control watching
harvest serve --no-watch         # Static serve only (no file watching)
harvest serve --debounce-ms 500  # Faster file change detection
harvest serve --only-ext py,ts   # Watch only Python/TypeScript files
```

### harvest query - Search and filter data
```bash
harvest query [OPTIONS] <harvest.json>

# Basic queries
harvest query data.json --entity files --language python
harvest query data.json --entity chunks --kind function
harvest query data.json --path-regex "src/.*\\.ts$"

# Advanced filtering
harvest query data.json --entity chunks --public true --min-lines 10
harvest query data.json --export-named "MyComponent" --has-default-export
harvest query data.json --symbol-regex "^test_.*" --fields path,symbol,start_line
```

### harvest watch - Monitor directory for changes
```bash
harvest watch [OPTIONS] <directory>

# Basic usage  
harvest watch .                          # Watch current dir → ./codebase.harvest.json
harvest watch /path/to/src -o out.json   # Custom output path
harvest watch . --debounce-ms 500        # Faster change detection
harvest watch . --only-ext py,js,ts      # Watch specific extensions only
```

### harvest sow - Generate artifacts
```bash
harvest sow [OPTIONS] <harvest.json>

# Generate React barrel exports
harvest sow data.json --react src/index.ts
```

## Output Control

Control what sections are included in harvest output:

- **`--include metadata`** - File inventory: paths, sizes, languages, modification times
- **`--include data`** - File contents: full source code of each file  
- **`--include chunks`** - Parsed symbols: functions, classes, exports with line ranges
- **`--exclude chunks`** - Skip code parsing (faster, smaller output)

**Common patterns:**
```bash
# Fast file catalog
harvest reap . --include metadata

# Source archive  
harvest reap . --exclude chunks

# LLM context preparation
harvest reap . --include chunks --format jsonl

# Full analysis dataset
harvest reap . --include metadata data chunks  # (default)
```

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

## Smart Filtering & File Handling

**Completely Skipped** (no paths, no content):
- Hidden files/directories (`.env`, `.git/`, `.vscode/`)
- Test directories (`tests/`, `__tests__/`, `spec/`, `e2e/`)
- Build artifacts (`dist/`, `build/`, `node_modules/`)
- Config files (`.ini`, `.cfg`, `.properties`)
- Logs & temp files (`.log`, `.tmp`, `.cache/`)
- Binary/media files (`.exe`, `.mp3`, `.db`)

**Path-Only Listing** (shows in file list, no content):
- Images (`.jpg`, `.png`, `.svg`, `.gif`)
- Fonts (`.ttf`, `.woff`, `.woff2`)  
- Documents (`.pdf`, `.doc`, `.ppt`)

**Fully Processed** (content + chunks):
- Source code files in supported languages
- Configuration files (JSON, YAML, TOML)
- Documentation (Markdown, text files)

Override with `--no-default-excludes` to include everything.

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