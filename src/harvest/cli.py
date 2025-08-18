#!/usr/bin/env python3
# CLI entry points: reap/query/sow/serve
from __future__ import annotations
import argparse, json, fnmatch, re, sys, os
from pathlib import Path
from .paths import resolve_reap_out, resolve_data_path
from .core import HarvestEngine, DEFAULT_MAX_BYTES, DEFAULT_MAX_FILES, detect_language
from .server import serve_harvest

def _write_atomic(path: str, payload: dict, fmt: str = "json") -> None:
  """Write payload to path atomically with format support"""
  tmp_path = path + ".tmp"
  if fmt == "jsonl":
    # Write each item in data and chunks as separate JSON lines
    with open(tmp_path, "w", encoding="utf-8") as f:
      for item in payload.get("data", []):
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
      for item in payload.get("chunks", []):
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
  else:
    # Default JSON format
    with open(tmp_path, "w", encoding="utf-8") as f:
      json.dump(payload, f, indent=2, ensure_ascii=False)
  
  # Atomic rename
  os.rename(tmp_path, path)


def cmd_reap(args):
  """Create a harvest from local dir or GitHub URL."""
  engine = HarvestEngine(
    max_bytes=args.max_bytes,
    max_files=args.max_files,
    apply_default_excludes=(not args.no_default_excludes)
  )
  
  payload = engine.harvest_local(args.target)
  
  # Determine what to include based on flags
  include_set = set(args.include)
  if args.exclude:
    include_set -= set(args.exclude)
  
  # Build filtered payload
  filtered_payload = {}
  if "metadata" in include_set:
    filtered_payload["metadata"] = payload["metadata"]
  if "data" in include_set:
    filtered_payload["data"] = payload.get("data", [])
  if "chunks" in include_set:
    filtered_payload["chunks"] = payload.get("chunks", [])
  
  out = resolve_reap_out(args.out, os.getcwd())
  
  _write_atomic(out, filtered_payload, fmt=args.format)
  if args.mirror_out:
    _write_atomic(os.path.abspath(args.mirror_out), filtered_payload, fmt=args.format)
  
  # Report what was included
  included = list(include_set)
  meta = payload["metadata"]
  stats = []
  if "metadata" in include_set:
    stats.append(f"files={meta['counts']['total_files']}")
  if "chunks" in include_set:
    stats.append(f"chunks={len(payload.get('chunks', []))}")
  
  print(f"Created {out}  {' '.join(stats)}  included={','.join(sorted(included))}")
  if args.mirror_out:
    print(f"Mirrored to {args.mirror_out}")

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
  """Serve a local web UI with live updates (watch + serve by default)."""
  # Watch mode is now the default, use --no-watch to disable
  if not args.no_watch:
    from .server import serve_with_watch
    serve_with_watch(
      source=args.harvest_or_dir,
      port=args.port,
      debounce_ms=args.debounce_ms,
      poll=args.poll,
      include_ext=args.only_ext,
      exclude_ext=args.skip_ext,
    )
  else:
    # Static serve mode (no watching)
    path = resolve_data_path(args.harvest_or_dir, os.getcwd())
    
    # If file doesn't exist, create it by harvesting the directory
    if not os.path.exists(path):
      # Determine if path points to a directory that needs harvesting
      dir_to_harvest = os.path.dirname(path) if path.endswith('.json') else args.harvest_or_dir or os.getcwd()
      
      # Only harvest if the directory exists
      if os.path.isdir(dir_to_harvest):
        print(f"No harvest file found at {path}, creating one...")
        from .core import HarvestEngine
        engine = HarvestEngine(apply_default_excludes=True)
        payload = engine.harvest_local(dir_to_harvest)
        _write_atomic(path, payload)
        print(f"Created {path}")
      else:
        print(f"Error: {path} does not exist and cannot harvest from {dir_to_harvest}")
        return 1
    
    serve_harvest(path, args.port)

def cmd_watch(args):
  """Watch a source directory and incrementally re-harvest on changes."""
  from .watch import run_watch
  out = resolve_reap_out(args.out, os.getcwd())
  run_watch(
    source=args.source,
    out_json=out,
    debounce_ms=args.debounce_ms,
    poll=args.poll,
    include_ext=args.only_ext,
    exclude_ext=args.skip_ext,
  )

def main(argv=None) -> int:
  """Main CLI entry point."""
  # Get version dynamically
  try:
    from importlib.metadata import version
    __version__ = version("harvest-code")
  except:
    __version__ = "1.4.1"
  
  ap = argparse.ArgumentParser(prog="harvest", description="Reap codebases into portable JSON + chunks; query & serve.")
  ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
  sub = ap.add_subparsers(dest="cmd", required=True)
  
  # reap command
  pr = sub.add_parser("reap", help="Create a harvest from local dir or GitHub URL.")
  pr.add_argument("target")
  pr.add_argument("-o", "--out", default=None, help="Output JSON path (default: ./codebase.harvest.json)")
  pr.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
  pr.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
  pr.add_argument("--format", choices=("json","jsonl"), default="json", help="Output format")
  pr.add_argument("--mirror-out", help="Optional second output path")
  pr.add_argument("--no-default-excludes", action="store_true",
                  help="Do not apply the built-in exclude lists (folders, extensions, lockfiles)")
  pr.add_argument("--include", nargs="+", choices=["metadata", "data", "chunks"], 
                  default=["metadata", "data", "chunks"],
                  help="What to include in output (default: all)")
  pr.add_argument("--exclude", nargs="+", choices=["metadata", "data", "chunks"],
                  help="What to exclude from output")
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
  pv = sub.add_parser("serve", help="Serve a local web UI with live updates (watch + serve).")
  pv.add_argument("harvest_or_dir", nargs="?", default=".", help="Path to harvest JSON or directory (default: current dir)")
  pv.add_argument("--port", type=int, default=8787)
  pv.add_argument("--no-watch", action="store_true", help="Disable watching for file changes")
  pv.add_argument("--debounce-ms", type=int, default=800, help="Debounce time in milliseconds")
  pv.add_argument("--poll", type=float, default=1.0, help="Polling interval in seconds")
  pv.add_argument("--only-ext", default=None, help="Comma-separated list of extensions to include")
  pv.add_argument("--skip-ext", default=None, help="Comma-separated list of extensions to exclude")
  pv.set_defaults(func=cmd_serve)
  
  # watch command
  pw = sub.add_parser("watch", help="Watch a source directory and incrementally re-harvest on changes")
  pw.add_argument("source", help="Path to source directory to watch")
  pw.add_argument("-o", "--out", required=False, help="Output harvest JSON file (default: ./codebase.harvest.json)")
  pw.add_argument("--debounce-ms", type=int, default=800, help="Debounce time in milliseconds")
  pw.add_argument("--poll", type=float, default=1.0, help="Polling interval in seconds")
  pw.add_argument("--only-ext", default=None, help="Comma-separated list of extensions to include (e.g. py,ts,js)")
  pw.add_argument("--skip-ext", default=None, help="Comma-separated list of extensions to exclude")
  pw.set_defaults(func=cmd_watch)
  
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