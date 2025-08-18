#!/usr/bin/env python3
# Core harvesting logic: file processing, chunk generation, data structures
from __future__ import annotations
import ast, fnmatch, hashlib, json, os, re, sys, time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Dict
from urllib.parse import urlparse
import urllib.request
from .constants import CANON_EXT

# --- constants / defaults ---
DEFAULT_MAX_BYTES = 524288
DEFAULT_MAX_FILES = 5000
# Skip completely (no paths, no content)
DEFAULT_SKIP_EXT = {
  # logs & temp (no value in seeing these)
  ".log",".tmp",".temp",".ds_store","_py.html",".coverage",
  # config files (usually boilerplate)
  ".ini",".cfg",".conf",".config",".properties",".env",".editorconfig",
  # databases & checkpoints (binary, huge)
  ".db",".sqlite",".sqlite3",".db-wal",".db-shm",".ckpt",".safetensors",
  # audio/video (binary, huge)
  ".wav",".mp3",".flac",".ogg",".m4a",".mp4",".mov",".avi",".mkv",".webm",
  # archives & bundles (binary)
  ".zip",".tar",".gz",".rar",".7z",".xz",".bz2",".zst",
  # binaries & objects (no source value)
  ".exe",".dll",".so",".dylib",".o",".obj",".a",".lib",".wasm",".pyc",".dat",
  # misc large/generated
  ".bak",".dir",".lock",".min.js",".min.css",".map",
  # notebooks & ML artifacts (often huge/binary)
  ".ipynb",".pt",".onnx",".h5",".pth",".npz",".npy",".pb",".tflite"
}

# List paths only (no content) - files we want to know exist but don't need content
DEFAULT_PATH_ONLY_EXT = {
  # images & fonts (useful to know they exist, but content is binary)
  ".jpg",".jpeg",".png",".gif",".bmp",".svg",".ico",".tiff",".tif",".webp",".avif",".heic",
  ".ttf",".otf",".woff",".woff2",
  # documentation images/assets
  ".pdf",".doc",".docx",".ppt",".pptx"
}
DEFAULT_SKIP_FILES = {
  "index.jsx","index.tsx","__init__.py","harvest.json",
  # lockfiles (covered again below with LOCKFILE_NAMES in should_skip_path)
  "yarn.lock","package-lock.json","pnpm-lock.yaml","poetry.lock","Pipfile.lock","Cargo.lock","Gemfile.lock","composer.lock","go.sum"
}
DEFAULT_SKIP_FOLDERS = {
  "node_modules","vendor",
  ".git",".hg",".svn",
  "htmlcov","dist","build","out","bin","obj","target",
  "migrations",
  # test directories (often noisy/generated)
  "tests","test","__tests__","spec","e2e","cypress","playwright",
  "coverage","test-results","allure-results",
  # caches & tooling
  ".pytest_cache",".mypy_cache",".ruff_cache",".tox",".nox",".cache",".gradle",".ipynb_checkpoints",".dart_tool",".direnv",
  ".vscode",".idea",".next",".expo",".parcel-cache",".turbo",".yarn",".pnp",".nx",".nuxt",".svelte-kit",".angular",
  # site/docs/storybook artifacts
  "storybook-static",".docusaurus","site","public/build",
  # mobile / platform
  "Pods","DerivedData",
  "coverage","site-packages","__pycache__"
}

# Explicit lockfile names (kept separate for clarity in should_skip_path)
LOCKFILE_NAMES = {
  "yarn.lock","package-lock.json","pnpm-lock.yaml","poetry.lock","Pipfile.lock","Cargo.lock","Gemfile.lock","composer.lock","go.sum"
}
LANG_MAP = {".py":"python",".js":"javascript",".jsx":"javascriptreact",".ts":"typescript",".tsx":"typescriptreact",".json":"json",".md":"markdown",".yml":"yaml",".yaml":"yaml",".toml":"toml",".sh":"shell"}
IDENT = r"[A-Za-z_$][\w$]*"

def now_iso(): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
def detect_language(path:str): return LANG_MAP.get(Path(path).suffix.lower())
def sha256_text(s:str)->str: return hashlib.sha256(s.encode("utf-8","replace")).hexdigest()
def sha256_bytes(b:bytes)->str: return hashlib.sha256(b).hexdigest()

def is_github_url(s:str)->bool:
  try:
    u=urlparse(s)
    return u.netloc.lower()=="github.com" and len(u.path.strip("/").split("/"))>=2
  except: return False

def gh_headers()->Dict[str,str]:
  h={"Accept":"application/vnd.github+json","User-Agent":"harvest-cli"}
  tok=os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
  if tok: h["Authorization"]=f"Bearer {tok}"
  return h

def http_json(url:str, headers=None):
  req=urllib.request.Request(url, headers=headers or {})
  with urllib.request.urlopen(req, timeout=60) as r:
    return json.loads(r.read().decode("utf-8","replace"))

def http_get(url:str, headers=None)->bytes:
  req=urllib.request.Request(url, headers=headers or {})
  with urllib.request.urlopen(req, timeout=60) as r:
    return r.read()

# --- export extraction & chunkers ---
def extract_js_ts_exports(src:str, fname:str)->dict:
  default_name=None; named=set()
  m=re.search(rf"export\s+default\s+({IDENT})\b", src)
  if m: default_name=m.group(1)
  if not default_name:
    m=re.search(rf"export\s+default\s+function(?:\s+({IDENT}))?", src)
    if m: default_name=m.group(1) or fname
  if not default_name:
    m=re.search(rf"export\s+default\s+class(?:\s+({IDENT}))?", src)
    if m: default_name=m.group(1) or fname
  if not default_name:
    m=re.search(rf"export\s+default\s+(?:memo|forwardRef|observer|reactMemo)\(\s*({IDENT})\s*\)", src)
    if m: default_name=m.group(1)
  for m in re.finditer(rf"export\s+(?:const|let|var|function|class)\s+({IDENT})\b", src):
    named.add(m.group(1))
  for block in re.findall(r"export\s*\{\s*([^}]+)\s*\}", src, re.MULTILINE):
    for part in block.split(","):
      part=part.strip()
      if not part: continue
      m=re.match(rf"({IDENT})\s+as\s+({IDENT})", part)
      if m: named.add(m.group(2))
      else:
        m2=re.match(rf"({IDENT})", part)
        if m2: named.add(m2.group(1))
  for block in re.findall(r"module\.exports\s*=\s*\{([^}]+)\}", src, re.DOTALL):
    for part in block.split(","):
      part=part.strip()
      m=re.match(rf"({IDENT})\s*:", part) or re.match(rf"({IDENT})\b", part)
      if m: named.add(m.group(1))
  for m in re.finditer(rf"exports\.({IDENT})\s*=", src): named.add(m.group(1))
  return {"default": default_name, "named": sorted(named)}

def js_ts_chunks(src:str, path:str)->List[dict]:
  lines=src.splitlines(); loc=len(lines); starts=[]
  def add(match, kind, sym):
    line=src.count("\n", 0, match.start())+1
    starts.append((line,kind,sym))
  for m in re.finditer(rf"^export\s+default\s+function(?:\s+({IDENT}))?", src, re.MULTILINE):
    add(m, "export_default", m.group(1) or Path(path).stem)
  for m in re.finditer(rf"^export\s+default\s+({IDENT})", src, re.MULTILINE):
    add(m, "export_default_ref", m.group(1))
  for m in re.finditer(rf"^export\s+(?:const|let|var|function|class)\s+({IDENT})\b", src, re.MULTILINE):
    add(m, "export_named", m.group(1))
  for m in re.finditer(rf"^export\s+default\s+(?:memo|forwardRef|observer|reactMemo)\(\s*({IDENT})\s*\)", src, re.MULTILINE):
    add(m, "export_default_ref", m.group(1))
  for m in re.finditer(rf"^const\s+([A-Z][A-Za-z0-9_]*)\s*=\s*\(", src, re.MULTILINE):
    add(m, "component_const", m.group(1))
  for m in re.finditer(rf"^function\s+({IDENT})\s*\(", src, re.MULTILINE):
    add(m, "function", m.group(1))
  for m in re.finditer(rf"^class\s+({IDENT})\b", src, re.MULTILINE):
    add(m, "class", m.group(1))
  if not starts:
    return [{"id": chunk_id(path,1,loc), "file_path": path, "language": detect_language(path), "kind": "file", "symbol": Path(path).name, "start_line": 1, "end_line": loc, "public": False, "hash": sha256_text(src)}]
  starts.sort(); chunks=[]
  for i, (line,kind,sym) in enumerate(starts):
    start,end=line, starts[i+1][0]-1 if i+1<len(starts) else loc
    is_public=kind.startswith("export")
    chunks.append({"id": chunk_id(path,start,end), "file_path": path, "language": detect_language(path), "kind": kind, "symbol": sym, "start_line": start, "end_line": end, "public": is_public, "hash": sha256_text("\\n".join(lines[start-1:end]))})
  return chunks

def extract_py_symbols(src:str)->dict:
  try:
    t=ast.parse(src); syms=[]
    for node in ast.walk(t):
      if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        syms.append(node.name)
    return {"named": sorted(syms)}
  except: return {"named": []}

def py_chunks(src:str, path:str)->List[dict]:
  try:
    lines=src.splitlines(); loc=len(lines); tree=ast.parse(src); chunks=[]
    for node in ast.walk(tree):
      if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        start,end=node.lineno, node.end_lineno or node.lineno
        kind={"FunctionDef":"function", "AsyncFunctionDef":"function", "ClassDef":"class"}[type(node).__name__]
        is_public=not node.name.startswith("_")
        chunks.append({"id": chunk_id(path,start,end), "file_path": path, "language": "python", "kind": kind, "symbol": node.name, "start_line": start, "end_line": end, "public": is_public, "hash": sha256_text("\\n".join(lines[start-1:end]))})
    if not chunks:
      return [{"id": chunk_id(path,1,loc), "file_path": path, "language": "python", "kind": "file", "symbol": Path(path).name, "start_line": 1, "end_line": loc, "public": False, "hash": sha256_text(src)}]
    return chunks
  except:
    lines=src.splitlines(); loc=len(lines)
    return [{"id": chunk_id(path,1,loc), "file_path": path, "language": "python", "kind": "file", "symbol": Path(path).name, "start_line": 1, "end_line": loc, "public": False, "hash": sha256_text(src)}]

def chunk_id(path: str, start: int, end: int) -> str:
  # Content-agnostic: only path + line range
  key = f"{path}:{start}:{end}"
  return sha256_text(key)

@dataclass
class ChunkEntry:
  id: str; file_path: str; language: Optional[str]; kind: str; symbol: str
  start_line: int; end_line: int; public: bool; hash: str

@dataclass
class FileEntry:
  name: str; path: str; size: int; mtime: float; language: Optional[str]
  hash: str; truncated: bool; truncated_reason: Optional[str]
  exports: Optional[dict]; py_symbols: Optional[dict]; content: str

class HarvestEngine:
  def __init__(self, max_bytes=DEFAULT_MAX_BYTES, max_files=DEFAULT_MAX_FILES, 
               skip_ext=None, skip_files=None, skip_folders=None,
               path_only_ext=None, apply_default_excludes=True):
    self.max_bytes = max_bytes
    self.max_files = max_files
    self.skip_ext = skip_ext or DEFAULT_SKIP_EXT
    self.skip_files = skip_files or DEFAULT_SKIP_FILES
    self.skip_folders = skip_folders or DEFAULT_SKIP_FOLDERS
    self.path_only_ext = path_only_ext or DEFAULT_PATH_ONLY_EXT
    self.apply_default_excludes = apply_default_excludes
  
  def should_skip_path(self, path: Path) -> bool:
    if not self.apply_default_excludes: return False
    if path.suffix.lower() in self.skip_ext: return True
    
    # Skip all hidden files and directories (starting with .)
    for part in path.parts:
      if part.startswith('.') and part not in ['.', '..']:
        return True
    
    # Never index any *.harvest.json file
    if path.name.endswith(CANON_EXT):
      return True
    
    if path.name in self.skip_files: return True
    # Skip harvest.json pattern files
    if path.name.endswith('.harvest.json'): return True
    # skip explicit lockfiles
    if path.name in LOCKFILE_NAMES:
        return True
    for part in path.parts:
      if part in self.skip_folders: return True
    return False
  
  def should_path_only(self, path: Path) -> bool:
    """Check if this file should be listed but without content"""
    if not self.apply_default_excludes: return False
    return path.suffix.lower() in self.path_only_ext
  
  def process_file(self, path: Path, content: str = None) -> tuple[FileEntry, List[ChunkEntry]]:
    # Check if this is a path-only file (no content needed)
    path_only = self.should_path_only(path)
    
    if path_only:
      # For path-only files, don't read content
      content = ""
      truncated = False
      truncated_reason = "path_only"
    else:
      if content is None:
        try:
          content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
          content = ""
      
      # Handle truncation
      truncated = len(content.encode("utf-8")) > self.max_bytes
      truncated_reason = "size_limit" if truncated else None
      if truncated:
        # Truncate but try to end at line boundary
        byte_content = content.encode("utf-8")[:self.max_bytes]
        try:
          content = byte_content.decode("utf-8")
          # Find last complete line
          last_newline = content.rfind("\\n")
          if last_newline > 0:
            content = content[:last_newline+1]
        except UnicodeDecodeError:
          content = byte_content.decode("utf-8", errors="replace")
    
    lang = detect_language(str(path))
    
    # Extract exports/symbols (skip for path-only files)
    exports = None
    py_symbols = None
    if not path_only:
      if lang in ("javascript", "javascriptreact", "typescript", "typescriptreact"):
        exports = extract_js_ts_exports(content, path.stem)
      elif lang == "python":
        py_symbols = extract_py_symbols(content)
    
    # Create file entry
    file_entry = FileEntry(
      name=path.name,
      path=str(path),
      size=path.stat().st_size if path.exists() else 0,  # Use actual file size for path-only
      mtime=path.stat().st_mtime if path.exists() else 0,
      language=lang,
      hash=sha256_text(content) if content else "",
      truncated=truncated,
      truncated_reason=truncated_reason,
      exports=exports,
      py_symbols=py_symbols,
      content=content
    )
    
    # Generate chunks (skip for path-only files)
    chunks = []
    if not path_only:
      if lang in ("javascript", "javascriptreact", "typescript", "typescriptreact"):
        chunk_data = js_ts_chunks(content, str(path))
      elif lang == "python":
        chunk_data = py_chunks(content, str(path))
      else:
        # Generic file chunk
        lines = content.splitlines()
        chunk_data = [{
          "id": chunk_id(str(path), 1, len(lines)),
          "file_path": str(path),
          "language": lang,
          "kind": "file", 
          "symbol": path.name,
          "start_line": 1,
          "end_line": len(lines),
          "public": False,
          "hash": sha256_text(content)
        }]
      
      for chunk in chunk_data:
        chunks.append(ChunkEntry(**chunk))
    
    return file_entry, chunks
  
  def harvest_local(self, root_path: str) -> dict:
    root = Path(root_path).resolve()
    files = []
    chunks = []
    file_count = 0
    
    for file_path in root.rglob("*"):
      if not file_path.is_file(): continue
      if self.should_skip_path(file_path.relative_to(root)): continue
      
      file_count += 1
      if file_count > self.max_files:
        break
      
      try:
        file_entry, file_chunks = self.process_file(file_path)
        # Make paths relative to root
        rel_path = str(file_path.relative_to(root))
        file_entry.path = rel_path
        file_entry.name = file_path.name
        
        for chunk in file_chunks:
          chunk.file_path = rel_path
        
        files.append(asdict(file_entry))
        chunks.extend([asdict(c) for c in file_chunks])
      except Exception as e:
        print(f"Warning: skipped {file_path}: {e}", file=sys.stderr)
        continue
    
    # Count files by language
    files_by_language = {}
    for f in files:
      lang = f.get("language")
      if lang:
        files_by_language[lang] = files_by_language.get(lang, 0) + 1
    
    return {
      "metadata": {
        "source": {
          "type": "local",
          "root": str(root),
          "branch": None,
          "subpath": ""
        },
        "counts": {
          "total_files": len(files),
          "total_bytes": sum(f["size"] for f in files),
          "files_by_language": files_by_language
        },
        "created_at": now_iso(),
        "schema": "harvest/v1.2",
        "delta": {"added": 0, "removed": 0, "changed": 0}
      },
      "data": files,
      "chunks": chunks
    }

# -----------------------------
# Skeleton rendering (deterministic)
# -----------------------------
def render_python_skeleton(src: str) -> str:
  """
  Return only decorators, class/def signatures, and pass/docstring stubs.
  Deterministic: no formatting randomness; stable ordering as in source.
  """
  try:
    tree = ast.parse(src)
  except SyntaxError:
    # Fallback: best-effort header grep
    headers = []
    decos = []
    for line in src.splitlines():
      if line.lstrip().startswith("@"):
        decos.append(line.rstrip())
      elif re.match(r"^\s*(class|def)\s+\w+", line):
        headers.extend(decos); decos = []
        headers.append(line.split(":")[0].rstrip()+":")
    headers.extend(decos)
    return "\n".join(headers)

  lines = src.splitlines()
  out = []
  class _V(ast.NodeVisitor):
    def _decos(self, node):
      # Pull raw decorator lines from source via lineno
      for d in getattr(node, "decorator_list", []):
        # approximate: take the line where decorator starts
        ln = getattr(d, "lineno", None)
        if ln and 1 <= ln <= len(lines):
          out.append(lines[ln-1].rstrip())
    def visit_FunctionDef(self, node: ast.FunctionDef):
      self._decos(node)
      # Build argument list with type annotations
      args = []
      for i, arg in enumerate(node.args.args):
        arg_str = arg.arg
        if arg.annotation:
          try:
            arg_str += f": {ast.unparse(arg.annotation)}"
          except:
            pass
        args.append(arg_str)
      args_str = ", ".join(args)
      
      # Add return type if present
      ret_str = ""
      if node.returns:
        try:
          ret_str = f" -> {ast.unparse(node.returns)}"
        except:
          pass
      
      sig = f"def {node.name}({args_str}){ret_str}:"
      out.append(sig)
      self.generic_visit(node)
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
      self._decos(node)
      # Build argument list with type annotations
      args = []
      for i, arg in enumerate(node.args.args):
        arg_str = arg.arg
        if arg.annotation:
          try:
            arg_str += f": {ast.unparse(arg.annotation)}"
          except:
            pass
        args.append(arg_str)
      args_str = ", ".join(args)
      
      # Add return type if present
      ret_str = ""
      if node.returns:
        try:
          ret_str = f" -> {ast.unparse(node.returns)}"
        except:
          pass
      
      sig = f"async def {node.name}({args_str}){ret_str}:"
      out.append(sig)
      self.generic_visit(node)
    def visit_ClassDef(self, node: ast.ClassDef):
      self._decos(node)
      bases = []
      for b in node.bases:
        try:
          bases.append(ast.unparse(b))
        except Exception:
          bases.append(getattr(getattr(b, "id", None), "id", None) or "…")
      base_str = f"({', '.join(bases)})" if bases else ""
      out.append(f"class {node.name}{base_str}:")
      self.generic_visit(node)
  _V().visit(tree)
  return "\n".join(out)

_JS_FUNC_RE = re.compile(r"^(export\s+)?(async\s+)?function\s+([A-Za-z0-9_]+)\s*\([^)]*\)\s*{", re.M)
_JS_CLASS_RE = re.compile(r"^(export\s+)?class\s+([A-Za-z0-9_]+)\s*(extends\s+[A-Za-z0-9_\.]+)?\s*{", re.M)
_JS_EXPORTS_RE = re.compile(r"^export\s+(default\s+)?(const|let|var|function|class)\s+([A-Za-z0-9_]+)", re.M)

def render_js_ts_skeleton(src: str) -> str:
  headers = []
  for m in _JS_CLASS_RE.finditer(src):
    ex = (m.group(3) or "").strip()
    cls = m.group(2)
    headers.append(("export " if m.group(1) else "") + f"class {cls} {ex}".rstrip()+" { … }")
  for m in _JS_FUNC_RE.finditer(src):
    name = m.group(3)
    headers.append(("export " if m.group(1) else "") + f"function {name}(…) {{ … }}")
  for m in _JS_EXPORTS_RE.finditer(src):
    dflt = "default " if (m.group(1) or "").strip() else ""
    kind = m.group(2); name = m.group(3)
    headers.append(f"export {dflt}{kind} {name} …")
  return "\n".join(dict.fromkeys(headers))  # stable, unique, keep order

def render_skeleton(language: str|None, src: str) -> str:
  lang = (language or "").lower()
  if lang.startswith("py"): return render_python_skeleton(src)
  if "typescript" in lang or lang.startswith("ts"): return render_js_ts_skeleton(src)
  if "javascript" in lang or lang.startswith("js"): return render_js_ts_skeleton(src)
  # fallback: simple headers for C-like
  heads = []
  for ln in src.splitlines():
    if re.match(r"^\s*(class|[A-Za-z_][A-Za-z0-9_]*\s+\**[A-Za-z_][A-Za-z0-9_]*\s*\([^;{]*\)\s*)[{;]", ln):
      heads.append(ln.strip().rstrip("{") + " { … }")
  return "\n".join(heads)