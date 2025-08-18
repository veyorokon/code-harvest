#!/usr/bin/env python3
# Web server for harvest UI and API
from __future__ import annotations
import json, re, fnmatch, os
from http.server import SimpleHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from .ui import SERVE_HTML
from .core import render_skeleton

class ServeState:
  def __init__(self, payload, harvest_path=None):
    self._initial_payload = payload
    self.harvest_path = harvest_path
  
  @property
  def payload(self):
    """Get current payload, reloading from file if harvest_path is set (watch mode)"""
    if self.harvest_path:
      try:
        from pathlib import Path
        return json.loads(Path(self.harvest_path).read_text(encoding="utf-8"))
      except Exception:
        # Fall back to initial payload if file read fails
        return self._initial_payload
    return self._initial_payload

def make_handler(state: ServeState):
  class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args): pass  # suppress logs
    
    def _no_store_headers(self, *, etag: str = None, ctype: str = "application/json"):
      self.send_header("Content-Type", f"{ctype}; charset=utf-8")
      self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
      self.send_header("Pragma", "no-cache")
      self.send_header("Expires", "0")
      if etag:
        self.send_header("ETag", etag)
    
    def _harvest_stats(self, out_json_path: str):
      st = os.stat(out_json_path)
      # Weak ETag from mtime_ns/size (fast, good enough for local dev)
      etag = f'W/"{st.st_mtime_ns}-{st.st_size}"'
      return st, etag
    
    def send_json(self, obj, *, no_store=False, etag=None):
      data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
      self.send_response(200)
      if no_store:
        self._no_store_headers(etag=etag)
      else:
        self.send_header("Content-Type", "application/json; charset=utf-8")
      self.send_header("Content-Length", str(len(data)))
      self.end_headers()
      self.wfile.write(data)
    
    def do_GET(self):
      if self.path == "/" or self.path.startswith("/?"):
        data = SERVE_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        return
      
      if self.path == "/api/meta":
        # Always read from disk to get fresh version updates from watcher
        if state.harvest_path:
          try:
            _, etag = self._harvest_stats(state.harvest_path)
            # Check If-None-Match for 304 response
            inm = self.headers.get("If-None-Match")
            if inm and inm == etag:
              self.send_response(304)
              self.end_headers()
              return
            
            with open(state.harvest_path, "r", encoding="utf-8") as f:
              fresh_payload = json.load(f)
            meta = fresh_payload.get("metadata", {})
            # Include version + server-side etag for client cache busting
            body = {"version": int(meta.get("version", 0)), **meta, "etag": etag}
            self.send_json(body, no_store=True, etag=etag)
          except Exception:
            meta = state.payload.get("metadata", {})
            self.send_json(meta, no_store=True)
        else:
          meta = state.payload.get("metadata", {})
          self.send_json(meta, no_store=True)
        return
      
      if self.path.startswith("/api/search"):
        u = urlparse(self.path); qs = parse_qs(u.query)
        ent = qs.get("entity", ["files"])[0]
        items = state.payload.get("chunks" if ent == "chunks" else "data", [])
        lang = qs.get("language", [None])[0]; kind = qs.get("kind", [None])[0]
        path_regex = qs.get("path_regex", [None])[0]; sym_regex = qs.get("symbol_regex", [None])[0]
        fields_param = qs.get("fields", [None])[0]
        wanted = [f.strip() for f in fields_param.split(",")] if fields_param else None
        
        # Pagination parameters
        limit_param = qs.get("limit", [None])[0]
        cursor_param = qs.get("cursor", ["0"])[0]
        limit = int(limit_param) if limit_param else None
        cursor = int(cursor_param) if cursor_param else 0
        
        # Filter items
        filtered = []
        for it in items:
          if lang and it.get("language") != lang: continue
          if kind and it.get("kind") != kind: continue
          path = it.get("path") or it.get("file_path")
          if path_regex and not re.search(path_regex, path): continue
          if sym_regex and not re.search(sym_regex, it.get("symbol") or ""): continue
          filtered.append({k: it.get(k) for k in wanted} if wanted else it)
        
        # Apply pagination if limit specified
        if limit:
          total = len(filtered)
          start_idx = cursor
          end_idx = min(start_idx + limit, total)
          page_items = filtered[start_idx:end_idx]
          next_cursor = end_idx if end_idx < total else None
          
          result = {
            "items": page_items,
            "total": total,
            "cursor": cursor,
            "limit": limit,
            "next_cursor": next_cursor,
            "has_more": next_cursor is not None
          }
        else:
          # Non-paginated (backward compatibility)
          result = filtered
        
        self.send_json(result, no_store=True)
        return
      
      if self.path == "/api/harvest":
        # Return the full harvest JSON with no-store headers
        if state.harvest_path:
          try:
            _, etag = self._harvest_stats(state.harvest_path)
            # Check If-None-Match for 304 response
            inm = self.headers.get("If-None-Match")
            if inm and inm == etag:
              self.send_response(304)
              self.end_headers()
              return
            
            self.send_response(200)
            self._no_store_headers(etag=etag, ctype="application/json")
            self.end_headers()
            with open(state.harvest_path, "rb") as f:
              self.wfile.write(f.read())
          except Exception:
            # Fallback to in-memory payload
            self.send_json(state.payload, no_store=True)
        else:
          self.send_json(state.payload, no_store=True)
        return
      
      if self.path.startswith("/api/export"):
        # Export filtered items as NDJSON (JSONL)
        u = urlparse(self.path); qs = parse_qs(u.query)
        ent = qs.get("entity", ["chunks"])[0]  # default chunks
        items = state.payload.get("chunks" if ent == "chunks" else "data", [])
        lang = qs.get("language", [None])[0]; kind = qs.get("kind", [None])[0]
        path_regex = qs.get("path_regex", [None])[0]; sym_regex = qs.get("symbol_regex", [None])[0]
        fields_param = qs.get("fields", [None])[0]
        wanted = [f.strip() for f in fields_param.split(",")] if fields_param else None
        
        # Filter
        def _match(it):
          if lang and it.get("language") != lang: return False
          if kind and it.get("kind") != kind: return False
          path = it.get("path") or it.get("file_path")
          if path_regex and not re.search(path_regex, path): return False
          if sym_regex and not re.search(sym_regex, it.get("symbol") or ""): return False
          return True
        
        # Headers
        name = "harvest_export.jsonl"
        data = [it for it in items if _match(it)]
        self.send_response(200)
        self._no_store_headers(ctype="application/x-ndjson")
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.end_headers()
        for it in data:
          row = ({k: it.get(k) for k in wanted} if wanted else it)
          line = (json.dumps(row, ensure_ascii=False) + "\\n").encode("utf-8")
          self.wfile.write(line)
        return
      
      if self.path.startswith("/api/file"):
        u = urlparse(self.path); qs = parse_qs(u.query)
        file_path = qs.get("path", [None])[0]
        start = int(qs.get("start", ["1"])[0])
        end_param = qs.get("end", [""])[0]
        end = int(end_param) if end_param else 0
        want_skel = qs.get("skeleton", ["0"])[0] in ("1","true","yes")
        
        if not file_path:
          self.send_response(400)
          self.end_headers()
          return
        
        # Find file in data
        file_data = None
        for f in state.payload.get("data", []):
          if f.get("path") == file_path:
            file_data = f
            break
        
        if not file_data:
          self.send_json({"error": "File not found", "path": file_path})
          return
        
        content = file_data.get("content", "")
        lines = content.splitlines()
        
        if end > 0:
          # Specific line range
          selected_lines = lines[start-1:end]
        else:
          # From start to end of file
          selected_lines = lines[start-1:]
        
        result_text = "\n".join(selected_lines)
        
        # Optional: render skeleton view instead of raw content
        if want_skel:
          lang = file_data.get("language")
          result_text = render_skeleton(lang, result_text)
        
        self.send_json({
          "path": file_path,
          "start": start,
          "end": end if end > 0 else len(lines),
          "text": result_text
        }, no_store=True)
        return
      
      # Default 404
      self.send_response(404)
      self._no_store_headers(ctype="text/plain")
      self.end_headers()
  
  return Handler

def serve_harvest(harvest_path: str, port: int = 8787):
  """Start HTTP server for harvest UI"""
  import json
  from pathlib import Path
  
  payload = json.loads(Path(harvest_path).read_text(encoding="utf-8"))
  state = ServeState(payload, harvest_path)
  handler = make_handler(state)
  
  server = HTTPServer(("localhost", port), handler)
  print(f"Serving harvest at http://localhost:{port}")
  try:
    server.serve_forever()
  except KeyboardInterrupt:
    print("\\nServer stopped")
  finally:
    server.server_close()

def serve_with_watch(source: str, port: int = 8787, debounce_ms: int = 800, 
                     poll: float = 1.0, include_ext: str = None, exclude_ext: str = None):
  """Start HTTP server with integrated file watching"""
  import threading, tempfile, os, json, time
  from pathlib import Path
  from .watch import run_watch
  
  # Create temp harvest file
  temp_dir = tempfile.gettempdir()
  harvest_file = os.path.join(temp_dir, f"harvest-live-{port}.json")
  
  # Initial harvest
  print(f"[harvest] creating initial harvest from {source}")
  try:
    from .core import HarvestEngine
    engine = HarvestEngine()
    payload = engine.harvest_local(source)
    
    # Add initial version for watch mode
    payload.setdefault("metadata", {})["version"] = 0
    
    with open(harvest_file, "w", encoding="utf-8") as f:
      json.dump(payload, f, ensure_ascii=False, indent=2)
    
    print(f"[harvest] created {harvest_file}")
  except Exception as e:
    print(f"[harvest] initial harvest failed: {e}")
    return
  
  # Start watcher in background thread
  stop_watch = threading.Event()
  
  def watch_worker():
    run_watch(
      source=source,
      out_json=harvest_file,
      debounce_ms=debounce_ms,
      poll=poll,
      include_ext=include_ext,
      exclude_ext=exclude_ext,
      _test_stop_event=stop_watch,
    )
  
  watch_thread = threading.Thread(target=watch_worker, daemon=True)
  watch_thread.start()
  
  # Give watcher a moment to start
  time.sleep(0.5)
  
  # Start server
  payload = json.loads(Path(harvest_file).read_text(encoding="utf-8"))
  state = ServeState(payload, harvest_file)
  handler = make_handler(state)
  
  server = HTTPServer(("localhost", port), handler)
  print(f"Serving live harvest at http://localhost:{port}")
  print(f"[harvest] watching {source} → {harvest_file} (poll={poll}s, debounce={debounce_ms}ms)")
  print("Press Ctrl+C to stop")
  
  try:
    server.serve_forever()
  except KeyboardInterrupt:
    print(f"\\n[harvest] stopping watch and server")
    stop_watch.set()
    server.server_close()
    # Clean up temp file
    try:
      os.unlink(harvest_file)
    except:
      pass