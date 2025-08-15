#!/usr/bin/env python3
# Core CLI: reap/query/sow/serve, chunks + incremental (no third-party deps)
from __future__ import annotations
import argparse, ast, fnmatch, hashlib, json, os, re, sys, time
from dataclasses import dataclass, asdict
from http.server import SimpleHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import List, Optional, Dict
from urllib.parse import urlparse, parse_qs
import urllib.request

# --- constants / defaults ---
DEFAULT_MAX_BYTES = 524288
DEFAULT_MAX_FILES = 5000
DEFAULT_SKIP_EXT = {".log",".ds_store","_py.html",".coverage",".wav",".db",".mp4",".mp3",".jpg",".jpeg",".png",".gif",".bmp",".svg",".ico",".tiff",".tif",".pdf",".zip",".tar",".gz",".rar",".7z",".exe",".dll",".pyc",".dat",".bak",".dir",".lock",".min.js",".min.css",".ipynb",".pt",".onnx",".h5",".pth",".npz",".npy"}
DEFAULT_SKIP_FILES = {"index.jsx","index.tsx","__init__.py"}
DEFAULT_SKIP_FOLDERS = {"node_modules",".git","htmlcov","dist","build","migrations",".pytest_cache","logs",".venv","__pycache__", ".mypy_cache",".ruff_cache",".vscode",".idea",".next",".expo",".parcel-cache",".turbo","coverage","site-packages"}
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
    return [{"file_path":path,"language":detect_language(path),"kind":"file","symbol":Path(path).stem,"start_line":1,"end_line":loc,"public":False}]
  starts=sorted(set(starts))
  chunks=[]
  for i,(line,kind,sym) in enumerate(starts):
    end=starts[i+1][0]-1 if i+1<len(starts) else loc
    chunks.append({"file_path":path,"language":detect_language(path),"kind":kind,"symbol":sym,"start_line":line,"end_line":max(line,end),"public":kind.startswith("export")})
  return chunks

def py_chunks(src:str, path:str):
  symbols={"functions":[],"classes":[],"all":[]}; chunks=[]
  try: tree=ast.parse(src)
  except Exception:
    lines=src.splitlines()
    return [{"file_path":path,"language":"python","kind":"file","symbol":Path(path).stem,"start_line":1,"end_line":len(lines),"public":False}], symbols
  for node in tree.body:
    if isinstance(node, ast.FunctionDef):
      symbols["functions"].append(node.name)
      chunks.append({"file_path":path,"language":"python","kind":"function","symbol":node.name,"start_line":getattr(node,"lineno",1),"end_line":getattr(node,"end_lineno",getattr(node,"lineno",1)),"public":not node.name.startswith("_")})
    elif isinstance(node, ast.ClassDef):
      symbols["classes"].append(node.name)
      chunks.append({"file_path":path,"language":"python","kind":"class","symbol":node.name,"start_line":getattr(node,"lineno",1),"end_line":getattr(node,"end_lineno",getattr(node,"lineno",1)),"public":not node.name.startswith("_")})
    elif isinstance(node, ast.Assign):
      for t in node.targets:
        if isinstance(t, ast.Name) and t.id=="__all__":
          try:
            v=ast.literal_eval(node.value)
            if isinstance(v,(list,tuple)): symbols["all"]=[str(x) for x in v]
          except Exception: pass
  symbols["functions"].sort(); symbols["classes"].sort()
  return chunks, symbols

@dataclass
class FileEntry:
  name:str; path:str; size:int; mtime:float|None; language:str|None; hash:str|None; truncated:bool; truncated_reason:str|None; exports:dict|None; py_symbols:dict|None; content:str|None

@dataclass
class ChunkEntry:
  id:str; file_path:str; language:str|None; kind:str; symbol:str; start_line:int; end_line:int; public:bool; hash:str|None

def extract_lines(src:str, start:int, end:int)->str:
  if not src: return ""
  lines=src.splitlines()
  start=max(1,start); end=min(len(lines), end)
  return "\n".join(lines[start-1:end])

def chunk_id(path:str, start:int, end:int)->str:
  return sha256_text(f"{path}:{start}:{end}")

def should_skip(rel:str, skip_ext:set, skip_files:set, skip_folders:set, only_ext:set|None)->bool:
  p=Path(rel)
  if any(part in skip_folders for part in p.parts): return True
  if p.name in skip_files: return True
  ext=p.suffix.lower()
  if only_ext is not None and ext not in only_ext: return True
  if ext in skip_ext: return True
  return False

def try_git_ls_files(root:Path):
  import subprocess
  try:
    out=subprocess.check_output(["git","-C",str(root),"ls-files"], stderr=subprocess.DEVNULL)
    return [ln.strip() for ln in out.decode().splitlines() if ln.strip()]
  except Exception: return None

def summarize(source_type:str, root:str, files:List[FileEntry], branch:str|None=None, subpath:str|None=None)->dict:
  by_lang={}; total=0
  for f in files:
    if f.language: by_lang[f.language]=by_lang.get(f.language,0)+1
    total+=f.size
  return {"source":{"type":source_type,"root":root,"branch":branch,"subpath":subpath or ""},"counts":{"total_files":len(files),"total_bytes":total,"files_by_language":by_lang},"created_at":now_iso(),"schema":"harvest/v1.2"}

def build_prev_index(prev_path:Path|None):
  if not prev_path: return None
  try:
    payload=json.loads(prev_path.read_text(encoding="utf-8"))
    idx={f["path"]:f for f in payload.get("data",[])}
    ch_index={}
    for ch in payload.get("chunks",[]): ch_index.setdefault(ch["file_path"], []).append(ch)
    idx["__chunks__"]=ch_index
    return idx
  except Exception: return None

def compute_delta(prev:dict|None, cur_files:List[FileEntry])->dict:
  if not prev: return {"added":0,"removed":0,"changed":0}
  prev_set={p for p in prev if p!="__chunks__"}
  cur_set={f.path for f in cur_files}
  added=len(cur_set - prev_set); removed=len(prev_set - cur_set)
  changed=sum(1 for p in (cur_set & prev_set) if (prev[p].get("hash") != next((f.hash for f in cur_files if f.path==p), None) or prev[p].get("size") != next((f.size for f in cur_files if f.path==p), None)))
  return {"added":added,"removed":removed,"changed":changed}

def harvest_local(root:Path, *, max_bytes:int, max_files:int, only_ext:set|None, skip_ext:set, skip_files:set, skip_folders:set, no_content:bool, prev_index:dict|None):
  files=[]; chunks=[]
  listed = try_git_ls_files(root) or [str(Path(r)/fn) for r,ds,fs in os.walk(root) for fn in fs if not any(d in skip_folders for d in Path(r).parts)]
  n=0
  for file_path in listed[:max_files]:
    abs_p = root / file_path if not os.path.isabs(file_path) else Path(file_path)
    if not abs_p.exists(): continue
    rel=abs_p.relative_to(root).as_posix()
    if should_skip(rel, skip_ext, skip_files, skip_folders, only_ext): continue
    st=abs_p.stat(); size=st.st_size; mtime=st.st_mtime
    truncated=no_content or size>max_bytes
    reason="no-content" if no_content else ("size" if size>max_bytes else None)
    lang=detect_language(rel)
    prev_f=(prev_index or {}).get(rel)
    reuse= prev_f and prev_f.get("size")==size and prev_f.get("mtime")==mtime
    content_text=None; file_hash=None
    if reuse:
      fe=FileEntry(**prev_f); files.append(fe)
      for ch in (prev_index.get("__chunks__",{}).get(rel) or []): chunks.append(ChunkEntry(**ch))
    else:
      raw=None
      if not truncated:
        try: raw=abs_p.read_bytes()
        except Exception: truncated=True; reason="read-failed"
      if raw is not None:
        file_hash=sha256_bytes(raw)
        content_text=raw.decode("utf-8","replace")
      fe=FileEntry(Path(rel).name, rel, size, mtime, lang, file_hash, truncated, reason, None, None, content_text)
      if lang in {"javascript","javascriptreact","typescript","typescriptreact"}:
        src=content_text or ""
        fe.exports=extract_js_ts_exports(src, Path(rel).stem)
        for c in js_ts_chunks(src, rel):
          text=extract_lines(src, c["start_line"], c["end_line"])
          chunks.append(ChunkEntry(chunk_id(rel,c["start_line"],c["end_line"]), rel, c["language"], c["kind"], c["symbol"], c["start_line"], c["end_line"], c["public"], sha256_text(text) if text else None))
      elif lang=="python":
        src=content_text or ""
        cks, syms=py_chunks(src, rel); fe.py_symbols=syms
        for c in cks:
          text=extract_lines(src, c["start_line"], c["end_line"])
          chunks.append(ChunkEntry(chunk_id(rel,c["start_line"],c["end_line"]), rel, c["language"], c["kind"], c["symbol"], c["start_line"], c["end_line"], c["public"], sha256_text(text) if text else None))
      else:
        if content_text:
          total_lines=len(content_text.splitlines())
          chunks.append(ChunkEntry(chunk_id(rel,1,total_lines), rel, lang, "file", Path(rel).stem, 1, total_lines, False, sha256_text(content_text)))
      files.append(fe)
    n+=1
  meta=summarize("local", str(root), files)
  return files, chunks, meta

# --- serve (no deps): serves UI + /api endpoints over HTTP ---
SERVE_HTML = """<!doctype html><meta charset=utf-8><title>Harvest</title>
<style>
  body{font-family:system-ui,sans-serif;margin:0}
  header{padding:12px 16px;box-shadow:0 1px 0 #ddd;position:sticky;top:0;background:#fff}
  main{padding:16px;display:grid;gap:12px;grid-template-columns: 1fr minmax(320px, 40%)}
  input,select{padding:6px 8px;margin-right:8px}
  table{border-collapse:collapse;width:100%}
  td,th{border-bottom:1px solid #eee;padding:6px 8px;text-align:left}
  tr:hover{background:#fafafa}
  pre{background:#0b1020;color:#e6e6e6;padding:12px;border-radius:8px;overflow:auto;white-space:pre}
  #pane{position:sticky;top:60px;height:calc(100vh - 88px)}
  #meta small{color:#666}
  .muted{color:#666}
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
  .truncate{max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:inline-block;vertical-align:bottom}
  .button{padding:6px 10px;border:1px solid #ddd;border-radius:8px;background:#fff;cursor:pointer}
  .button:active{transform:translateY(1px)}
</style>
<header><strong>Harvest</strong> · <span id=meta></span></header>
<main>
  <div>
    <div>
      <input id=q placeholder="symbol regex (chunks) or path regex (files)">
      <select id=entity><option>chunks</option><option>files</option></select>
      <select id=lang><option value="">language</option><option>python</option><option>javascript</option><option>javascriptreact</option><option>typescript</option><option>typescriptreact</option></select>
      <button id=go class="button">Search</button>
      <label class="muted" style="margin-left:8px;">
        <input type="checkbox" id="showTech"> Show technical columns
      </label>
      <span id=stats class="muted"></span>
    </div>
    <div>
      <table id=results><thead></thead><tbody></tbody></table>
    </div>
  </div>
  <aside id=pane>
    <div class="muted">Preview</div>
    <pre id=code>(click a chunk row)</pre>
  </aside>
</main>
<script>
const $ = sel => document.querySelector(sel);
const debounce = (fn, ms=200) => { let t; return (...a)=>{ clearTimeout(t); t=setTimeout(()=>fn(...a), ms); } };
const shorten = (s, head=8, tail=6) => !s ? "" : (s.length <= head+tail+1 ? s : s.slice(0,head)+"…"+s.slice(-tail));
const copy = async (text) => { try { await navigator.clipboard.writeText(text); } catch {} }

async function meta(){ const r=await fetch('api/meta'); const j=await r.json(); document.getElementById('meta').textContent = j.source.type + ' · ' + j.created_at + ' · files=' + j.counts.total_files; }
async function search(){
  const entity=document.getElementById('entity').value;
  const q=document.getElementById('q').value;
  const lang=document.getElementById('lang').value;
  const url=new URL('api/search', location.href);
  url.searchParams.set('entity', entity);
  if(q) url.searchParams.set(entity==='chunks' ? 'symbol_regex':'path_regex', q);
  if(lang) url.searchParams.set('language', lang);
  // choose columns (hide id/hash by default)
  const showTech = document.getElementById('showTech').checked;
  const baseCols = (entity==='chunks')
    ? ["file_path","symbol","kind","start_line","end_line","language","public"]
    : ["path","name","language","size"];
  const techCols = (entity==='chunks') ? ["id","hash"] : ["hash"];
  const cols = showTech ? baseCols.concat(techCols) : baseCols;
  url.searchParams.set('fields', cols.join(','));
  const t0=performance.now();
  const r=await fetch(url); const rows=await r.json();
  $("#stats").textContent = rows.length + " result(s) · " + Math.round(performance.now()-t0) + "ms";
  const thead=document.querySelector('#results thead'); const tbody=document.querySelector('#results tbody');
  thead.innerHTML=''; tbody.innerHTML='';
  if(rows.length===0){ thead.innerHTML='<tr><th>No results</th></tr>'; return; }
  thead.innerHTML='<tr>'+cols.map(c=>'<th>'+c.replace("_"," ")+'</th>').join('')+'</tr>';
  tbody.innerHTML=rows.map(x=>{
    const attrs = (entity==='chunks')
      ? `data-file="${x.file_path}" data-start="${x.start_line}" data-end="${x.end_line}"`
      : '';
    return '<tr '+attrs+'>'+cols.map(c=>{
      let v = x[c];
      if ((c==="id" || c==="hash") && v){
        const short = shorten(String(v));
        return `<td class="mono"><span class="truncate" title="${String(v)}">${short}</span> <button class="button mono" data-copy="${String(v)}" title="Copy ${c}">copy</button></td>`;
      }
      return '<td>'+String(v)+'</td>';
    }).join('')+'</tr>';
  }).join('');
  // row click → preview (chunks only)
  tbody.onclick = async (e) => {
    // copy buttons
    const btn = e.target.closest('button[data-copy]');
    if (btn) { copy(btn.dataset.copy); return; }
    const tr = e.target.closest('tr'); if (!tr) return;
    if (document.getElementById('entity').value !== 'chunks') return;
    const fp = tr.dataset.file, start = parseInt(tr.dataset.start||"1"), end = parseInt(tr.dataset.end||"0");
    const r2 = await fetch(`api/file?path=${encodeURIComponent(fp)}&start=${start}&end=${end}`);
    const j2 = await r2.json();
    document.getElementById('code').textContent = j2.text || '(no content available for this file)';
  }
}
meta(); search();
document.getElementById('go').onclick = search;
document.getElementById('q').oninput = debounce(search, 250);
document.getElementById('showTech').onchange = search;
</script>"""

class ServeState:
  def __init__(self, payload): self.payload=payload

def make_handler(state:ServeState):
  class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
      if self.path in ("/","/index.html"):
        self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.end_headers()
        self.wfile.write(SERVE_HTML.encode("utf-8")); return
      if self.path.startswith("/api/meta"):
        self.send_json(state.payload.get("metadata",{})); return
      if self.path.startswith("/api/search"):
        qs = parse_qs(urlparse(self.path).query)
        ent = (qs.get("entity",["files"])[0])
        items = state.payload.get("chunks" if ent=="chunks" else "data", [])
        lang = qs.get("language",[None])[0]; kind = qs.get("kind",[None])[0]
        path_regex = qs.get("path_regex",[None])[0]; sym_regex = qs.get("symbol_regex",[None])[0]
        fields_param = qs.get("fields",[None])[0]
        wanted = [f.strip() for f in fields_param.split(",")] if fields_param else None
        out = []
        for it in items:
          if lang and it.get("language")!=lang: continue
          if kind and it.get("kind")!=kind: continue
          path=it.get("path") or it.get("file_path")
          if path_regex and (re.search(path_regex, path) is None): continue
          if sym_regex and (re.search(sym_regex, it.get("symbol") or "") is None): continue
          out.append({k: it.get(k) for k in wanted} if wanted else it)
        self.send_json(out); return
      if self.path.startswith("/api/file"):
        qs = parse_qs(urlparse(self.path).query)
        path = qs.get("path", [None])[0]
        start = int(qs.get("start", ["1"])[0])
        end = int(qs.get("end", ["0"])[0])
        if not path:
            self.send_json({"error":"path required"}); return
        data = state.payload.get("data", [])
        text = ""
        for f in data:
            if f.get("path")==path:
                content = f.get("content") or ""
                lines = content.splitlines()
                if end <= 0 or end > len(lines): end = len(lines)
                start = max(1, start); end = max(start, end)
                text = "\n".join(lines[start-1:end])
                break
        self.send_json({"path": path, "start": start, "end": end, "text": text}); return
      self.send_response(404); self.end_headers()
    def send_json(self, obj):
      b=json.dumps(obj).encode("utf-8")
      self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
  return Handler

def cmd_serve(args):
  p=Path(args.harvest).resolve()
  payload=json.loads(p.read_text(encoding="utf-8"))
  state=ServeState(payload)
  Handler=make_handler(state)
  addr=("0.0.0.0", args.port)
  httpd=HTTPServer(addr, Handler)
  print(f"Serving {p} at http://{addr[0]}:{addr[1]}  (Ctrl+C to stop)")
  try: httpd.serve_forever()
  except KeyboardInterrupt: pass
  finally: httpd.server_close()

def cmd_reap(args):
  skip_ext=set(e.strip().lower() for e in args.skip_ext.split(",") if e.strip())
  skip_files=set(e.strip() for e in args.skip_file.split(",") if e.strip())
  skip_folders=set(e.strip() for e in args.skip_folder.split(",") if e.strip())
  only_ext=set(e.strip().lower() for e in args.only_ext.split(",") if e and e.strip()) if args.only_ext else None
  prev_idx=build_prev_index(Path(args.prev)) if args.prev else None
  root=Path(args.target).resolve()
  files,chunks,meta=harvest_local(root, max_bytes=args.max_bytes, max_files=args.max_files, only_ext=only_ext, skip_ext=skip_ext, skip_files=skip_files, skip_folders=skip_folders, no_content=args.no_content, prev_index=prev_idx)
  out=args.out or f"{root.name}.harvest.json"
  meta["delta"]=compute_delta(prev_idx, files)
  payload={"metadata":meta,"data":[asdict(f) for f in files],"chunks":[asdict(c) for c in chunks]}
  Path(out).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
  print(f"Created {out}  files={len(files)}  chunks={len(chunks)}  delta={meta['delta']}")

def cmd_query(args):
  payload=json.loads(Path(args.json).read_text(encoding="utf-8"))
  items=payload.get("chunks" if args.entity=="chunks" else "data", [])
  out=[]
  for it in items:
    if args.language and it.get("language")!=args.language: continue
    if args.kind and it.get("kind")!=args.kind: continue
    path=it.get("path") or it.get("file_path")
    if args.path_glob and not fnmatch.fnmatch(path, args.path_glob): continue
    if args.path_regex and not re.search(args.path_regex, path): continue
    if args.symbol_regex and not re.search(args.symbol_regex, it.get("symbol") or ""): continue
    if args.public and args.entity=="chunks":
      want=(args.public=="true")
      if bool(it.get("public"))!=want: continue
    if args.min_lines and args.entity=="chunks":
      if (it.get("end_line",0)-it.get("start_line",0)+1)<args.min_lines: continue
    if args.max_lines and args.entity=="chunks":
      if (it.get("end_line",0)-it.get("start_line",0)+1)>args.max_lines: continue
    if args.export_named and args.entity=="files":
      exp=(it.get("exports") or {}).get("named", [])
      if args.export_named not in exp: continue
    if args.has_default_export and args.entity=="files":
      if not (it.get("exports") or {}).get("default"): continue
    out.append(it)
  if not args.fields:
    for x in out: print(json.dumps(x, ensure_ascii=False))
  else:
    fields=[f.strip() for f in args.fields.split(",")]
    for x in out: print("\t".join(str(x.get(f,'')) for f in fields))

def cmd_sow(args):
  if not args.react_out: print("Only --react is supported currently for 'sow'.", file=sys.stderr); return 2
  payload=json.loads(Path(args.json).read_text(encoding="utf-8"))
  exports=[]
  for f in payload.get("data",[]):
    if not f.get("exports"): continue
    p=f["path"]
    if not any(p.endswith(ext) for ext in (".js",".jsx",".ts",".tsx")): continue
    e=f["exports"]; exports.append({"path":p,"default":e.get("default"),"named":e.get("named",[])})
  from collections import OrderedDict
  imports=OrderedDict(); exported=OrderedDict()
  import re as _re
  def norm(p): return "./"+_re.sub(r"\.(jsx|tsx|js|ts)$","",p.replace("\\","/")).lstrip("./")
  for it in exports:
    ip=norm(it["path"]); spec=imports.setdefault(ip,set())
    d=it.get("default")
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
  outp=Path(args.react_out)
  with outp.open("w", encoding="utf-8") as w:
    for ip,names in imports.items(): w.write(f'import {{ {", ".join(sorted(names))} }} from "{ip}";\n')
    w.write("\nexport {\n"); w.write(",\n".join(exported.keys())); w.write("\n};\n")
  print(f"Created {args.react_out}  imports={len(imports)}  exports={len(exported)}")

def main(argv=None)->int:
  ap=argparse.ArgumentParser(prog="harvest", description="Reap codebases into portable JSON + chunks; query & serve.")
  sub=ap.add_subparsers(dest="cmd", required=True)
  
  pr=sub.add_parser("reap", help="Create a harvest from local dir or GitHub URL.")
  pr.add_argument("target"); pr.add_argument("-o","--out", default=None)
  pr.add_argument("--prev", help="Reuse previous harvest & compute delta.")
  pr.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
  pr.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
  pr.add_argument("--no-content", action="store_true")
  pr.add_argument("--only-ext", default=None)
  pr.add_argument("--skip-ext", default=",".join(sorted(DEFAULT_SKIP_EXT)))
  pr.add_argument("--skip-file", default=",".join(sorted(DEFAULT_SKIP_FILES)))
  pr.add_argument("--skip-folder", default=",".join(sorted(DEFAULT_SKIP_FOLDERS)))
  pr.set_defaults(func=cmd_reap)

  ps=sub.add_parser("sow", help="Generate artifacts from a harvest (React barrel).")
  ps.add_argument("json"); ps.add_argument("--react", dest="react_out")
  ps.set_defaults(func=cmd_sow)

  pq=sub.add_parser("query", help="Query files or chunks.")
  pq.add_argument("json"); pq.add_argument("--entity", choices=["files","chunks"], default="files")
  pq.add_argument("--language"); pq.add_argument("--kind")
  pq.add_argument("--path-glob"); pq.add_argument("--path-regex"); pq.add_argument("--symbol-regex")
  pq.add_argument("--export-named"); pq.add_argument("--has-default-export", action="store_true")
  pq.add_argument("--public", choices=["true","false"])
  pq.add_argument("--min-lines", type=int); pq.add_argument("--max-lines", type=int)
  pq.add_argument("--fields")
  pq.set_defaults(func=cmd_query)

  pv=sub.add_parser("serve", help="Serve a local web UI and JSON API for a harvest.")
  pv.add_argument("harvest"); pv.add_argument("--port", type=int, default=8787)
  pv.set_defaults(func=cmd_serve)

  args=ap.parse_args(argv)
  return args.func(args) or 0

if __name__=="__main__": sys.exit(main())