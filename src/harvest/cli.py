#!/usr/bin/env python3
# CLI entry points: reap/query/sow/serve
from __future__ import annotations
import argparse, json, fnmatch, re, sys
from pathlib import Path
from .core import HarvestEngine, DEFAULT_MAX_BYTES, DEFAULT_MAX_FILES, detect_language
from .server import serve_harvest

def cmd_reap(args):
  """Create a harvest from local dir or GitHub URL."""
  engine = HarvestEngine(
    max_bytes=args.max_bytes,
    max_files=args.max_files
  )
  
  payload = engine.harvest_local(args.target)
  
  out = args.out or "harvest.json"
  Path(out).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
  
  meta = payload["metadata"]
  print(f"Created {out}  files={meta['counts']['total_files']}  chunks={len(payload['chunks'])}  delta={meta['delta']}")

def cmd_query(args):
  """Query files or chunks."""
  payload = json.loads(Path(args.json).read_text(encoding="utf-8"))
  items = payload.get("chunks" if args.entity == "chunks" else "data", [])
  out = []
  
  for it in items:
    if args.language and it.get("language") != args.language: continue
    if args.kind and it.get("kind") != args.kind: continue
    path = it.get("path") or it.get("file_path")
    if args.path_glob and not fnmatch.fnmatch(path, args.path_glob): continue
    if args.path_regex and not re.search(args.path_regex, path): continue
    if args.symbol_regex and not re.search(args.symbol_regex, it.get("symbol") or ""): continue
    if args.public and args.entity == "chunks":
      want = (args.public == "true")
      if bool(it.get("public")) != want: continue
    if args.min_lines and args.entity == "chunks":
      if (it.get("end_line", 0) - it.get("start_line", 0) + 1) < args.min_lines: continue
    if args.max_lines and args.entity == "chunks":
      if (it.get("end_line", 0) - it.get("start_line", 0) + 1) > args.max_lines: continue
    if args.export_named and args.entity == "files":
      exp = (it.get("exports") or {}).get("named", [])
      if args.export_named not in exp: continue
    if args.has_default_export and args.entity == "files":
      if not (it.get("exports") or {}).get("default"): continue
    out.append(it)
  
  if not args.fields:
    for x in out: print(json.dumps(x, ensure_ascii=False))
  else:
    fields = [f.strip() for f in args.fields.split(",")]
    for x in out: print("\\t".join(str(x.get(f, '')) for f in fields))

def cmd_sow(args):
  """Generate artifacts from a harvest (React barrel)."""
  if not args.react_out: 
    print("Only --react is supported currently for 'sow'.", file=sys.stderr)
    return 2
  
  payload = json.loads(Path(args.json).read_text(encoding="utf-8"))
  exports = []
  
  for f in payload.get("data", []):
    if not f.get("exports"): continue
    p = f["path"]
    if not any(p.endswith(ext) for ext in (".js", ".jsx", ".ts", ".tsx")): continue
    e = f["exports"]
    exports.append({"path": p, "default": e.get("default"), "named": e.get("named", [])})
  
  from collections import OrderedDict
  imports = OrderedDict()
  exported = OrderedDict()
  import re as _re
  
  def norm(p): 
    return "./" + _re.sub(r"\\.(jsx|tsx|js|ts)$", "", p.replace("\\\\", "/")).lstrip("./")
  
  for it in exports:
    ip = norm(it["path"])
    spec = imports.setdefault(ip, set())
    d = it.get("default")
    if d:
      alias = d
      i = 2
      while alias in exported and exported[alias] != ip:
        alias = f"{d}{i}"
        i += 1
      spec.add(f"default as {alias}")
      exported.setdefault(alias, ip)
    for n in it.get("named") or []:
      alias = n
      i = 2
      while alias in exported and exported[alias] != ip:
        alias = f"{n}{i}"
        i += 1
      spec.add(alias)
      exported.setdefault(alias, ip)
  
  outp = Path(args.react_out)
  with outp.open("w", encoding="utf-8") as w:
    for ip, names in imports.items(): 
      w.write(f'import {{ {", ".join(sorted(names))} }} from "{ip}";\\n')
    w.write("\\nexport {\\n")
    w.write(",\\n".join(exported.keys()))
    w.write("\\n};\\n")
  
  print(f"Created {args.react_out}  imports={len(imports)}  exports={len(exported)}")

def cmd_serve(args):
  """Serve a local web UI and JSON API for a harvest."""
  serve_harvest(args.harvest, args.port)

def main(argv=None) -> int:
  """Main CLI entry point."""
  ap = argparse.ArgumentParser(prog="harvest", description="Reap codebases into portable JSON + chunks; query & serve.")
  sub = ap.add_subparsers(dest="cmd", required=True)
  
  # reap command
  pr = sub.add_parser("reap", help="Create a harvest from local dir or GitHub URL.")
  pr.add_argument("target")
  pr.add_argument("-o", "--out", default=None)
  pr.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
  pr.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
  pr.set_defaults(func=cmd_reap)
  
  # query command
  pq = sub.add_parser("query", help="Query files or chunks.")
  pq.add_argument("json")
  pq.add_argument("--entity", choices=["files", "chunks"], default="files")
  pq.add_argument("--language")
  pq.add_argument("--kind")
  pq.add_argument("--path-glob")
  pq.add_argument("--path-regex")
  pq.add_argument("--symbol-regex")
  pq.add_argument("--export-named")
  pq.add_argument("--has-default-export", action="store_true")
  pq.add_argument("--public", choices=["true", "false"])
  pq.add_argument("--min-lines", type=int)
  pq.add_argument("--max-lines", type=int)
  pq.add_argument("--fields")
  pq.set_defaults(func=cmd_query)
  
  # sow command
  ps = sub.add_parser("sow", help="Generate artifacts from a harvest (React barrel).")
  ps.add_argument("json")
  ps.add_argument("--react", dest="react_out")
  ps.set_defaults(func=cmd_sow)
  
  # serve command
  pv = sub.add_parser("serve", help="Serve a local web UI and JSON API for a harvest.")
  pv.add_argument("harvest")
  pv.add_argument("--port", type=int, default=8787)
  pv.set_defaults(func=cmd_serve)
  
  args = ap.parse_args(argv)
  
  try:
    return args.func(args) or 0
  except KeyboardInterrupt:
    return 130
  except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    return 1

if __name__ == "__main__":
  sys.exit(main())