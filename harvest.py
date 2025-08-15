#!/usr/bin/env python3
# harvest v1.1 — chunks + query + incremental (no deps)

from __future__ import annotations
import argparse, ast, fnmatch, hashlib, json, os, re, sys, time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from urllib.parse import urlparse
import urllib.request

# ---------- config ----------
DEFAULT_MAX_BYTES = 524288  # 512 KiB
DEFAULT_MAX_FILES = 5000
DEFAULT_SKIP_EXT = {
    ".log",".ds_store","_py.html",".coverage",".wav",".db",".mp4",".mp3",".jpg",".jpeg",".png",".gif",
    ".bmp",".svg",".ico",".tiff",".tif",".pdf",".zip",".tar",".gz",".rar",".7z",".exe",".dll",".pyc",
    ".dat",".bak",".dir",".lock",".min.js",".min.css",".ipynb",".pt",".onnx",".h5",".pth",".npz",".npy"
}
DEFAULT_SKIP_FILES = {"index.jsx", "index.tsx", "__init__.py"}
DEFAULT_SKIP_FOLDERS = {
    "node_modules",".git","htmlcov","dist","build","migrations",".pytest_cache","logs",".venv","__pycache__",
    ".mypy_cache",".ruff_cache",".vscode",".idea",".next",".expo",".parcel-cache",".turbo","coverage","site-packages"
}
LANG_MAP = {
    ".py":"python",".js":"javascript",".jsx":"javascriptreact",".ts":"typescript",".tsx":"typescriptreact",
    ".json":"json",".md":"markdown",".yml":"yaml",".yaml":"yaml",".toml":"toml",".sh":"shell"
}

# ---------- utils ----------
def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def detect_language(path: str) -> Optional[str]:
    return LANG_MAP.get(Path(path).suffix.lower())

def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def read_bytes_safely(p: Path) -> Optional[bytes]:
    try: return p.read_bytes()
    except Exception: return None

def is_github_url(s: str) -> bool:
    try:
        u = urlparse(s)
        return u.netloc.lower() == "github.com" and len(u.path.strip("/").split("/")) >= 2
    except: return False

def gh_headers() -> Dict[str,str]:
    h = {"Accept":"application/vnd.github+json","User-Agent":"harvest-cli"}
    tok = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if tok: h["Authorization"] = f"Bearer {tok}"
    return h

def http_json(url: str, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8","replace"))

def http_get(url: str, headers=None) -> bytes:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()

# ---------- export extraction & chunkers ----------
IDENT = r"[A-Za-z_$][\w$]*"

def extract_js_ts_exports(src: str, fname_no_ext: str) -> dict:
    default_name = None; named = set()
    m = re.search(rf"export\s+default\s+({IDENT})\b", src)
    if m: default_name = m.group(1)
    if not default_name:
        m = re.search(rf"export\s+default\s+function(?:\s+({IDENT}))?", src)
        if m: default_name = m.group(1) or fname_no_ext
    if not default_name:
        m = re.search(rf"export\s+default\s+class(?:\s+({IDENT}))?", src)
        if m: default_name = m.group(1) or fname_no_ext
    if not default_name:
        m = re.search(rf"export\s+default\s+(?:memo|forwardRef|observer|reactMemo)\(\s*({IDENT})\s*\)", src)
        if m: default_name = m.group(1)
    for m in re.finditer(rf"export\s+(?:const|let|var|function|class)\s+({IDENT})\b", src):
        named.add(m.group(1))
    for block in re.findall(r"export\s*{\s*([^}}]+)\s*}", src, re.MULTILINE):
        for part in block.split(","):
            part = part.strip()
            if not part: continue
            m = re.match(rf"({IDENT})\s+as\s+({IDENT})", part)
            if m: named.add(m.group(2))
            else:
                m2 = re.match(rf"({IDENT})", part)
                if m2: named.add(m2.group(1))
    # CommonJS
    for block in re.findall(r"module\.exports\s*=\s*{([^}}]+)}", src, re.DOTALL):
        for part in block.split(","):
            part = part.strip()
            m = re.match(rf"({IDENT})\s*:", part) or re.match(rf"({IDENT})\b", part)
            if m: named.add(m.group(1))
    for m in re.finditer(rf"exports\.({IDENT})\s*=", src): named.add(m.group(1))
    return {"default": default_name, "named": sorted(named)}

def js_ts_chunks(src: str, path: str) -> List[dict]:
    """approximate top-level chunking for JS/TS (exports, functions/classes, components)."""
    lines = src.splitlines()
    loc = len(lines)
    # gather start positions (line numbers 1-based)
    starts: List[Tuple[int,str,str]] = []  # (line, kind, symbol)
    # exports (likely public)
    for m in re.finditer(rf"^export\s+default\s+function(?:\s+({IDENT}))?", src, re.MULTILINE):
        name = m.group(1) or Path(path).stem; line = src.count("\n", 0, m.start()) + 1
        starts.append((line,"export_default",name))
    for m in re.finditer(rf"^export\s+default\s+({IDENT})", src, re.MULTILINE):
        name = m.group(1); line = src.count("\n", 0, m.start()) + 1
        starts.append((line,"export_default_ref",name))
    for m in re.finditer(rf"^export\s+(?:const|let|var|function|class)\s+({IDENT})\b", src, re.MULTILINE):
        name = m.group(1); line = src.count("\n", 0, m.start()) + 1
        starts.append((line,"export_named",name))
    # components (heuristic)
    for m in re.finditer(rf"^export\s+default\s+(?:memo|forwardRef|observer|reactMemo)\(\s*({IDENT})\s*\)", src, re.MULTILINE):
        name = m.group(1); line = src.count("\n", 0, m.start()) + 1
        starts.append((line,"export_default_ref",name))
    for m in re.finditer(rf"^const\s+([A-Z][A-Za-z0-9_]*)\s*=\s*\(", src, re.MULTILINE):
        name = m.group(1); line = src.count("\n", 0, m.start()) + 1
        starts.append((line,"component_const",name))
    for m in re.finditer(rf"^function\s+([A-Z][A-Za-z0-9_]*)\s*\(", src, re.MULTILINE):
        name = m.group(1); line = src.count("\n", 0, m.start()) + 1
        starts.append((line,"component_fn",name))
    # general functions/classes
    for m in re.finditer(rf"^function\s+({IDENT})\s*\(", src, re.MULTILINE):
        name = m.group(1); line = src.count("\n", 0, m.start()) + 1
        starts.append((line,"function",name))
    for m in re.finditer(rf"^class\s+({IDENT})\b", src, re.MULTILINE):
        name = m.group(1); line = src.count("\n", 0, m.start()) + 1
        starts.append((line,"class",name))
    if not starts:
        # single chunk fallback
        return [{"file_path": path,"language": detect_language(path),"kind":"file","symbol":Path(path).stem,
                 "start_line":1,"end_line":loc,"public":False}]
    starts = sorted({s for s in starts})  # dedupe by tuple
    chunks = []
    for i,(line,kind,sym) in enumerate(starts):
        end = starts[i+1][0]-1 if i+1<len(starts) else loc
        public = kind.startswith("export")
        chunks.append({"file_path":path,"language":detect_language(path),"kind":kind,"symbol":sym,
                       "start_line":line,"end_line":max(line,end),"public":public})
    return chunks

def py_chunks(src: str, path: str) -> Tuple[List[dict], dict]:
    """Per top-level def/class via AST; also return python symbols."""
    symbols = {"functions":[], "classes":[], "all":[]}
    chunks = []
    try:
        tree = ast.parse(src)
    except Exception:
        # fallback: one chunk
        lines = src.splitlines()
        return ([{"file_path":path,"language":"python","kind":"file","symbol":Path(path).stem,
                  "start_line":1,"end_line":len(lines),"public":False}],[]
               )[0], symbols  # type: ignore
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            symbols["functions"].append(node.name)
            chunks.append({
                "file_path":path,"language":"python","kind":"function","symbol":node.name,
                "start_line":getattr(node,"lineno",1),
                "end_line":getattr(node,"end_lineno",getattr(node,"lineno",1)),
                "public": not node.name.startswith("_")
            })
        elif isinstance(node, ast.ClassDef):
            symbols["classes"].append(node.name)
            chunks.append({
                "file_path":path,"language":"python","kind":"class","symbol":node.name,
                "start_line":getattr(node,"lineno",1),
                "end_line":getattr(node,"end_lineno",getattr(node,"lineno",1)),
                "public": not node.name.startswith("_")
            })
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "__all__":
                    try:
                        v = ast.literal_eval(node.value)
                        if isinstance(v,(list,tuple)):
                            symbols["all"] = [str(x) for x in v]
                    except Exception: pass
    symbols["functions"].sort(); symbols["classes"].sort()
    return chunks, symbols

# ---------- schema ----------
@dataclass
class FileEntry:
    name: str
    path: str
    size: int
    mtime: Optional[float]
    language: Optional[str]
    hash: Optional[str]
    truncated: bool
    truncated_reason: Optional[str]
    exports: Optional[dict]        # js/ts exports
    py_symbols: Optional[dict]     # python symbols
    content: Optional[str]         # may be None

@dataclass
class ChunkEntry:
    id: str
    file_path: str
    language: Optional[str]
    kind: str
    symbol: str
    start_line: int
    end_line: int
    public: bool
    hash: Optional[str]            # hash of chunk text if available

# ---------- skip / selection ----------
def should_skip(rel: str, skip_ext: set, skip_files: set, skip_folders: set, only_ext: Optional[set]) -> bool:
    p = Path(rel)
    if any(part in skip_folders for part in p.parts): return True
    if p.name in skip_files: return True
    ext = p.suffix.lower()
    if only_ext is not None and ext not in only_ext: return True
    if ext in skip_ext: return True
    return False

# ---------- local harvesting ----------
def try_git_ls_files(root: Path) -> Optional[List[str]]:
    import subprocess
    try:
        out = subprocess.check_output(["git","-C",str(root),"ls-files"], stderr=subprocess.DEVNULL)
        return [ln.strip() for ln in out.decode().splitlines() if ln.strip()]
    except Exception:
        return None

def harvest_local(root: Path, *, max_bytes:int, max_files:int, only_ext:set|None,
                  skip_ext:set, skip_files:set, skip_folders:set, no_content:bool,
                  prev_index:dict|None) -> Tuple[List[FileEntry], List[ChunkEntry], dict]:
    files: List[FileEntry] = []; chunks: List[ChunkEntry] = []
    listed = try_git_ls_files(root) or [
        str(Path(r)/fn) for r,ds,fs in os.walk(root) for fn in fs if not any(d in skip_folders for d in Path(r).parts)
    ]
    total = 0
    for abs_path in (root/p for p in listed):
        rel = abs_path.relative_to(root).as_posix()
        if should_skip(rel, skip_ext, skip_files, skip_folders, only_ext): continue
        st = abs_path.stat()
        size, mtime = st.st_size, st.st_mtime
        truncated = no_content or size > max_bytes
        truncated_reason = "no-content" if no_content else ("size" if size>max_bytes else None)
        lang = detect_language(rel)

        prev_file = (prev_index or {}).get(rel)
        reuse = prev_file and prev_file.get("size")==size and prev_file.get("mtime")==mtime

        content_text = None; file_hash = None

        if reuse:
            # reuse full entry (and its chunks) without re-reading
            fe = FileEntry(**prev_file)
            files.append(fe)
            for ch in (prev_index.get("__chunks__", {}).get(rel) or []):
                chunks.append(ChunkEntry(**ch))
        else:
            raw = read_bytes_safely(abs_path) if not truncated else None
            if raw is not None:
                file_hash = sha256_bytes(raw)
                content_text = raw.decode("utf-8","replace")
            fe = FileEntry(
                name=Path(rel).name, path=rel, size=size, mtime=mtime, language=lang,
                hash=file_hash, truncated=truncated, truncated_reason=truncated_reason,
                exports=None, py_symbols=None, content=content_text
            )
            if lang in {"javascript","javascriptreact","typescript","typescriptreact"}:
                src = content_text or ""
                fe.exports = extract_js_ts_exports(src, Path(rel).stem)
                for c in js_ts_chunks(src, rel):
                    chunk_text = extract_lines(src, c["start_line"], c["end_line"])
                    chunks.append(ChunkEntry(
                        id=chunk_id(rel, c["start_line"], c["end_line"], chunk_text, file_hash),
                        file_path=rel, language=c["language"], kind=c["kind"], symbol=c["symbol"],
                        start_line=c["start_line"], end_line=c["end_line"], public=c["public"],
                        hash=(sha256_text(chunk_text) if chunk_text else None)
                    ))
            elif lang == "python":
                src = content_text or ""
                cks, py_syms = py_chunks(src, rel)
                fe.py_symbols = py_syms
                for c in cks:
                    chunk_text = extract_lines(src, c["start_line"], c["end_line"])
                    chunks.append(ChunkEntry(
                        id=chunk_id(rel, c["start_line"], c["end_line"], chunk_text, file_hash),
                        file_path=rel, language=c["language"], kind=c["kind"], symbol=c["symbol"],
                        start_line=c["start_line"], end_line=c["end_line"], public=c["public"],
                        hash=(sha256_text(chunk_text) if chunk_text else None)
                    ))
            else:
                # non-code: single file chunk if content included
                if content_text:
                    total_lines = len(content_text.splitlines())
                    chunk_text = content_text
                    chunks.append(ChunkEntry(
                        id=chunk_id(rel,1,total_lines,chunk_text,file_hash),
                        file_path=rel, language=lang, kind="file", symbol=Path(rel).stem,
                        start_line=1, end_line=total_lines, public=False,
                        hash=(sha256_text(chunk_text) if chunk_text else None)
                    ))
            files.append(fe)
        total += 1
        if total >= max_files: break

    meta = summarize("local", str(root), files)
    return files, chunks, meta

# ---------- GitHub harvesting (tree + raw) ----------
def parse_gh(u: str) -> Tuple[str,str,Optional[str],Optional[str]]:
    pu = urlparse(u); parts = [p for p in pu.path.strip("/").split("/") if p]
    owner, repo = parts[0], parts[1]
    branch, sub = None, None
    if len(parts)>=3 and parts[2] in ("tree","blob"):
        branch = parts[3] if len(parts)>=4 else None
        sub = "/".join(parts[4:]) if len(parts)>=5 else None
    return owner, repo, branch, sub

def gh_default_branch(owner: str, repo: str) -> str:
    return http_json(f"https://api.github.com/repos/{owner}/{repo}", gh_headers()).get("default_branch","main")

def gh_tree(owner: str, repo: str, ref: str) -> List[dict]:
    return http_json(f"https://api.github.com/repos/{owner}/{repo}/git/trees/{ref}?recursive=1", gh_headers()).get("tree",[])

def gh_raw(owner: str, repo: str, ref: str, path: str) -> bytes:
    return http_get(f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}", gh_headers())

def harvest_github(url: str, *, max_bytes:int, max_files:int, only_ext:set|None,
                   skip_ext:set, skip_files:set, skip_folders:set, no_content:bool) -> Tuple[List[FileEntry], List[ChunkEntry], dict]:
    owner, repo, branch, sub = parse_gh(url)
    if branch is None: branch = gh_default_branch(owner, repo)
    tree = gh_tree(owner, repo, branch)

    files: List[FileEntry] = []; chunks: List[ChunkEntry] = []
    count = 0
    def in_scope(p: str) -> bool:
        return (not sub) or p==sub or p.startswith(sub.rstrip("/")+"/")

    for node in tree:
        if node.get("type") != "blob": continue
        rel = node["path"]
        if not in_scope(rel): continue
        if should_skip(rel, skip_ext, skip_files, skip_folders, only_ext): continue
        size = int(node.get("size") or 0)
        truncated = no_content or size>max_bytes
        reason = "no-content" if no_content else ("size" if size>max_bytes else None)
        lang = detect_language(rel)
        file_hash = None; content_text = None
        if not truncated:
            try:
                raw = gh_raw(owner, repo, branch, rel)
                file_hash = sha256_bytes(raw)
                content_text = raw.decode("utf-8","replace")
            except Exception: truncated, reason = True, "fetch-failed"
        fe = FileEntry(
            name=Path(rel).name, path=rel, size=size, mtime=None, language=lang,
            hash=file_hash, truncated=truncated, truncated_reason=reason,
            exports=None, py_symbols=None, content=content_text
        )
        if lang in {"javascript","javascriptreact","typescript","typescriptreact"}:
            src = content_text or ""
            fe.exports = extract_js_ts_exports(src, Path(rel).stem)
            for c in js_ts_chunks(src, rel):
                chunk_text = extract_lines(src, c["start_line"], c["end_line"])
                chunks.append(ChunkEntry(
                    id=chunk_id(rel,c["start_line"],c["end_line"],chunk_text,file_hash),
                    file_path=rel, language=c["language"], kind=c["kind"], symbol=c["symbol"],
                    start_line=c["start_line"], end_line=c["end_line"], public=c["public"],
                    hash=(sha256_text(chunk_text) if chunk_text else None)
                ))
        elif lang=="python":
            src = content_text or ""
            cks, py_syms = py_chunks(src, rel); fe.py_symbols = py_syms
            for c in cks:
                chunk_text = extract_lines(src, c["start_line"], c["end_line"])
                chunks.append(ChunkEntry(
                    id=chunk_id(rel,c["start_line"],c["end_line"],chunk_text,file_hash),
                    file_path=rel, language=c["language"], kind=c["kind"], symbol=c["symbol"],
                    start_line=c["start_line"], end_line=c["end_line"], public=c["public"],
                    hash=(sha256_text(chunk_text) if chunk_text else None)
                ))
        files.append(fe)
        count += 1
        if count>=max_files: break

    meta = summarize("github", f"https://github.com/{owner}/{repo}", files, branch=branch, subpath=sub)
    return files, chunks, meta

# ---------- helpers ----------
def extract_lines(src: str, start: int, end: int) -> str:
    if not src: return ""
    lines = src.splitlines()
    start = max(1, start); end = min(len(lines), end)
    return "\n".join(lines[start-1:end])

def chunk_id(path: str, start: int, end: int, text: Optional[str], file_hash: Optional[str]) -> str:
    base = f"{path}:{start}:{end}:"
    return sha256_text(base + (text if text is not None else (file_hash or "")))

def summarize(source_type: str, root: str, files: List[FileEntry], branch: str|None=None, subpath: str|None=None) -> dict:
    by_lang: Dict[str,int] = {}; total_bytes = 0
    for f in files:
        if f.language: by_lang[f.language] = by_lang.get(f.language,0)+1
        total_bytes += f.size
    meta = {"source":{"type":source_type,"root":root,"branch":branch,"subpath":subpath or ""},"counts":{
        "total_files":len(files), "total_bytes": total_bytes, "files_by_language": by_lang
    }, "created_at": now_iso(), "schema":"harvest/v1.1"}
    return meta

def build_prev_index(prev_path: Optional[Path]) -> dict|None:
    if not prev_path: return None
    try:
        payload = json.loads(prev_path.read_text(encoding="utf-8"))
        idx = {f["path"]:f for f in payload.get("data",[])}
        # stash chunks by file for fast reuse
        ch_index: Dict[str,List[dict]] = {}
        for ch in payload.get("chunks",[]):
            ch_index.setdefault(ch["file_path"], []).append(ch)
        idx["__chunks__"] = ch_index
        return idx
    except Exception:
        return None

def compute_delta(prev: dict|None, cur_files: List[FileEntry]) -> dict:
    if not prev: return {"added":0,"removed":0,"changed":0}
    prev_set = {p for p in prev if p not in ("__chunks__",)}
    cur_set  = {f.path for f in cur_files}
    added = len(cur_set - prev_set); removed = len(prev_set - cur_set)
    changed = sum(1 for p in (cur_set & prev_set) if (prev[p].get("hash") != next((f.hash for f in cur_files if f.path==p), None)
                                                    or prev[p].get("size") != next((f.size for f in cur_files if f.path==p), None)))
    return {"added":added, "removed":removed, "changed":changed}

# ---------- CLI ----------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harvest", description="Reap codebases into JSON, with chunks & query.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("reap", help="Create a harvest from local dir or GitHub URL.")
    pr.add_argument("target")
    pr.add_argument("-o","--out", default=None)
    pr.add_argument("--prev", help="Previous harvest.json to reuse unchanged files and compute delta.")
    pr.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    pr.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    pr.add_argument("--no-content", action="store_true")
    pr.add_argument("--only-ext", default=None, help="Comma list (e.g. .ts,.tsx,.py)")
    pr.add_argument("--skip-ext", default=",".join(sorted(DEFAULT_SKIP_EXT)))
    pr.add_argument("--skip-file", default=",".join(sorted(DEFAULT_SKIP_FILES)))
    pr.add_argument("--skip-folder", default=",".join(sorted(DEFAULT_SKIP_FOLDERS)))

    ps = sub.add_parser("sow", help="Generate artifacts from a harvest (React barrel).")
    ps.add_argument("json")
    ps.add_argument("--react", dest="react_out")

    pq = sub.add_parser("query", help="Query files or chunks.")
    pq.add_argument("json")
    pq.add_argument("--entity", choices=["files","chunks"], default="files")
    pq.add_argument("--language")
    pq.add_argument("--kind")
    pq.add_argument("--path-glob")
    pq.add_argument("--path-regex")
    pq.add_argument("--symbol-regex")
    pq.add_argument("--export-named")
    pq.add_argument("--has-default-export", action="store_true")
    pq.add_argument("--public", choices=["true","false"])
    pq.add_argument("--min-lines", type=int); pq.add_argument("--max-lines", type=int)
    pq.add_argument("--fields", help="Comma list of fields to print (default: JSON lines)")

    args = ap.parse_args(argv)

    if args.cmd == "reap":
        skip_ext = set(e.strip().lower() for e in args.skip_ext.split(",") if e.strip())
        skip_files = set(e.strip() for e in args.skip_file.split(",") if e.strip())
        skip_folders = set(e.strip() for e in args.skip_folder.split(",") if e.strip())
        only_ext = set(e.strip().lower() for e in args.only_ext.split(",") if e and e.strip()) if args.only_ext else None

        prev_idx = build_prev_index(Path(args.prev)) if args.prev else None

        if is_github_url(args.target):
            files, chunks, meta = harvest_github(args.target, max_bytes=args.max_bytes, max_files=args.max_files,
                                                 only_ext=only_ext, skip_ext=skip_ext, skip_files=skip_files,
                                                 skip_folders=skip_folders, no_content=args.no_content)
            out = args.out or f"{Path(urlparse(args.target).path).parts[-1]}.harvest.json"
        else:
            root = Path(args.target).resolve()
            files, chunks, meta = harvest_local(root, max_bytes=args.max_bytes, max_files=args.max_files,
                                                only_ext=only_ext, skip_ext=skip_ext, skip_files=skip_files,
                                                skip_folders=skip_folders, no_content=args.no_content,
                                                prev_index=prev_idx)
            out = args.out or f"{root.name}.harvest.json"

        meta["delta"] = compute_delta(prev_idx, files)
        payload = {"metadata": meta, "data":[asdict(f) for f in files], "chunks":[asdict(c) for c in chunks]}
        Path(out).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Created {out}  files={len(files)}  chunks={len(chunks)}  delta={meta['delta']}")
        return 0

    if args.cmd == "sow":
        if not args.react_out: print("Only --react is supported currently.", file=sys.stderr); return 2
        payload = json.loads(Path(args.json).read_text(encoding="utf-8"))
        exports = []
        for f in payload.get("data",[]):
            if not f.get("exports"): continue
            p = f["path"]
            if not any(p.endswith(ext) for ext in (".js",".jsx",".ts",".tsx")): continue
            e = f["exports"]; exports.append({"path":p,"default":e.get("default"),"named":e.get("named",[])})
        # assemble imports/exports
        from collections import OrderedDict
        imports: "OrderedDict[str,set]" = OrderedDict(); exported: "OrderedDict[str,str]" = OrderedDict()
        import re as _re
        def norm(p): return "./"+_re.sub(r"\.(jsx|tsx|js|ts)$","",p.replace("\\","/")).lstrip("./")
        for it in exports:
            ip = norm(it["path"]); spec = imports.setdefault(ip,set())
            d = it.get("default")
            if d:
                alias=d; i=2
                while alias in exported and exported[alias]!=ip:
                    alias=f"{d}{i}"; i+=1
                spec.add(f"default as {alias}"); exported.setdefault(alias, ip)
            for n in it.get("named") or []:
                alias=n; i=2
                while alias in exported and exported[alias]!=ip:
                    alias=f"{n}{i}"; i+=1
                spec.add(alias); exported.setdefault(alias, ip)
        outp = Path(args.react_out)
        with outp.open("w", encoding="utf-8") as w:
            for ip,names in imports.items(): w.write(f'import {{ {", ".join(sorted(names))} }} from "{ip}";\n')
            w.write("\nexport {\n"); w.write(",\n".join(exported.keys())); w.write("\n};\n")
        print(f"Created {args.react_out}  imports={len(imports)}  exports={len(exported)}")
        return 0

    if args.cmd == "query":
        payload = json.loads(Path(args.json).read_text(encoding="utf-8"))
        items = payload.get("chunks" if args.entity=="chunks" else "data", [])
        out = []
        for it in items:
            # filters
            if args.language and (it.get("language") != args.language): continue
            if args.kind and (it.get("kind") != args.kind): continue
            path = it.get("path") or it.get("file_path")
            if args.path_glob and not fnmatch.fnmatch(path, args.path_glob): continue
            if args.path_regex and not re.search(args.path_regex, path): continue
            if args.symbol_regex and not re.search(args.symbol_regex, it.get("symbol") or ""): continue
            if args.public and args.entity=="chunks":
                want = (args.public == "true")
                if bool(it.get("public")) != want: continue
            if args.min_lines and args.entity=="chunks":
                if (it.get("end_line",0) - it.get("start_line",0) + 1) < args.min_lines: continue
            if args.max_lines and args.entity=="chunks":
                if (it.get("end_line",0) - it.get("start_line",0) + 1) > args.max_lines: continue
            if args.export_named and args.entity=="files":
                exp = (it.get("exports") or {}).get("named", [])
                if args.export_named not in exp: continue
            if args.has_default_export and args.entity=="files":
                if not (it.get("exports") or {}).get("default"): continue
            out.append(it)
        # output
        if not args.fields:
            for x in out: print(json.dumps(x, ensure_ascii=False))
        else:
            fields = [f.strip() for f in args.fields.split(",")]
            for x in out:
                vals = []
                for f in fields:
                    vals.append(str(x.get(f,"")))
                print("\t".join(vals))
        return 0

    return 1

if __name__ == "__main__":
    sys.exit(main())
