#!/usr/bin/env python3
# Web server for harvest UI and API
from __future__ import annotations
import json, re, fnmatch
from http.server import SimpleHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from .ui import SERVE_HTML

class ServeState:
  def __init__(self, payload, harvest_path=None): 
    self.payload = payload
    self.harvest_path = harvest_path

def make_handler(state: ServeState):
  class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args): pass  # suppress logs
    def send_json(self, obj):
      data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
      self.send_response(200)
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
            with open(state.harvest_path, "r", encoding="utf-8") as f:
              fresh_payload = json.load(f)
            meta = fresh_payload.get("metadata", {})
          except Exception:
            meta = state.payload.get("metadata", {})
        else:
          meta = state.payload.get("metadata", {})
        self.send_json(meta)
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
        
        self.send_json(result)
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
        self.send_header("Content-Type", "application/x-ndjson")
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
        
        result_text = "\\n".join(selected_lines)
        self.send_json({
          "path": file_path,
          "start": start,
          "end": end if end > 0 else len(lines),
          "text": result_text
        })
        return
      
      # Default 404
      self.send_response(404)
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