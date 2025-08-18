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
  
  out = resolve_reap_out(args.out, args.target)
  
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
  out = resolve_reap_out(args.out, args.source)
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
  
  ap = argparse.ArgumentParser(
    prog="harvest", 
    description="Harvest codebases into portable JSON + chunks for RAG, analysis, and tooling.",
    epilog="Examples:\n"
           "  harvest serve                    # Watch + serve current directory\n"
           "  harvest reap . --include data    # Harvest just file contents\n"
           "  harvest reap . --format jsonl    # Output as JSONL for streaming\n"
           "  harvest query out.json --entity chunks --language python\n",
    formatter_class=argparse.RawDescriptionHelpFormatter
  )
  ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
  sub = ap.add_subparsers(dest="cmd", required=True)
  
  # reap command
  pr = sub.add_parser("reap", help="Create a harvest from local directory or GitHub URL.",
                      description="Extract files and code chunks from a codebase into structured JSON.")
  pr.add_argument("target", help="Local directory path or GitHub URL to harvest")
  pr.add_argument("-o", "--out", default=None, 
                  help="Output file path (default: ./codebase.harvest.json)")
  pr.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES,
                  help=f"Max bytes per file (default: {DEFAULT_MAX_BYTES})")
  pr.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES,
                  help=f"Max files to process (default: {DEFAULT_MAX_FILES})")
  pr.add_argument("--format", choices=("json","jsonl"), default="json", 
                  help="Output format: json (single object) or jsonl (line-delimited)")
  pr.add_argument("--mirror-out", help="Write a second copy to this path")
  pr.add_argument("--no-default-excludes", action="store_true",
                  help="Include hidden files, tests, node_modules, etc. (normally excluded)")
  pr.add_argument("--include", nargs="+", choices=["metadata", "data", "chunks"], 
                  default=["metadata", "data", "chunks"],
                  help="Sections to include: metadata (file info), data (file contents), chunks (parsed symbols)")
  pr.add_argument("--exclude", nargs="+", choices=["metadata", "data", "chunks"],
                  help="Sections to exclude from output")
  pr.set_defaults(func=cmd_reap)
  
  # query command
  pq = sub.add_parser("query", help="Search and filter harvest data.",
                      description="Query files or chunks with filters for language, symbols, exports, etc.")
  pq.add_argument("json", help="Path to harvest JSON file")
  pq.add_argument("--entity", choices=["files", "chunks"], default="files",
                  help="Query files or code chunks (default: files)")
  pq.add_argument("--language", help="Filter by programming language (e.g. python, javascript)")
  pq.add_argument("--kind", help="Filter chunks by kind (e.g. function, class, export)")
  pq.add_argument("--path-glob", help="Filter by file path glob pattern")
  pq.add_argument("--path-regex", help="Filter by file path regex")
  pq.add_argument("--symbol-regex", help="Filter chunks by symbol name regex")
  pq.add_argument("--export-named", help="Filter files that export specific named symbol")
  pq.add_argument("--has-default-export", action="store_true", help="Filter files with default exports")
  pq.add_argument("--public", choices=["true", "false"], help="Filter by public/private visibility")
  pq.add_argument("--min-lines", type=int, help="Minimum line count")
  pq.add_argument("--max-lines", type=int, help="Maximum line count")
  pq.add_argument("--fields", help="Comma-separated fields to output")
  pq.set_defaults(func=cmd_query)
  
  # sow command
  ps = sub.add_parser("sow", help="Generate code artifacts from harvest data.",
                      description="Transform harvest data into useful artifacts like React barrel exports.")
  ps.add_argument("json", help="Path to harvest JSON file")
  ps.add_argument("--react", dest="react_out", help="Generate React barrel file at this path")
  ps.set_defaults(func=cmd_sow)
  
  # serve command
  pv = sub.add_parser("serve", help="Start web UI with live updates (default mode).",
                      description="Serve interactive web interface with auto-refresh. Watches files by default.")
  pv.add_argument("harvest_or_dir", nargs="?", default=".", 
                  help="Directory to watch or harvest file to serve (default: current directory)")
  pv.add_argument("--port", type=int, default=8787, help="HTTP server port (default: 8787)")
  pv.add_argument("--no-watch", action="store_true", help="Disable file watching (static serve only)")
  pv.add_argument("--debounce-ms", type=int, default=800, 
                  help="File change debounce time in milliseconds (default: 800)")
  pv.add_argument("--poll", type=float, default=1.0, 
                  help="File system polling interval in seconds (default: 1.0)")
  pv.add_argument("--only-ext", default=None, 
                  help="Include only these extensions (comma-separated, e.g. py,ts,js)")
  pv.add_argument("--skip-ext", default=None, 
                  help="Exclude these extensions (comma-separated)")
  pv.set_defaults(func=cmd_serve)
  
  # watch command
  pw = sub.add_parser("watch", help="Watch directory and update harvest file on changes.",
                      description="Monitor source directory and incrementally update harvest when files change.")
  pw.add_argument("source", help="Source directory to watch for changes")
  pw.add_argument("-o", "--out", required=False, 
                  help="Output harvest file path (default: ./codebase.harvest.json)")
  pw.add_argument("--debounce-ms", type=int, default=800, 
                  help="Debounce file changes in milliseconds (default: 800)")
  pw.add_argument("--poll", type=float, default=1.0, 
                  help="Polling interval in seconds (default: 1.0)")
  pw.add_argument("--only-ext", default=None, 
                  help="Include only these extensions (comma-separated, e.g. py,ts,js)")
  pw.add_argument("--skip-ext", default=None, 
                  help="Exclude these extensions (comma-separated)")
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