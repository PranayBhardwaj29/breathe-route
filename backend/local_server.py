"""
Local Development Server for Breathe Route & Canopy Tree Recommender.
Runs a lightweight HTTP server on port 8000 that routes requests directly
into backend/app.py lambda_handler, matching AWS Lambda Function URL behavior,
and serves the frontend static directory.
"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import sys
import os
import mimetypes
from pathlib import Path

# Add backend directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import lambda_handler

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

class UnifiedAppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def _send_lambda_response(self, lambda_resp):
        status_code = lambda_resp.get("statusCode", 200)
        headers = lambda_resp.get("headers", {})
        body = lambda_resp.get("body", "{}").encode("utf-8")

        self.send_response(status_code)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        event = {
            "rawPath": self.path,
            "requestContext": {"http": {"method": "OPTIONS", "path": self.path}}
        }
        resp = lambda_handler(event, None)
        self._send_lambda_response(resp)

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else ""
        
        event = {
            "rawPath": self.path.split("?")[0],
            "path": self.path.split("?")[0],
            "requestContext": {"http": {"method": "POST", "path": self.path}},
            "body": raw_body
        }
        resp = lambda_handler(event, None)
        self._send_lambda_response(resp)

    def do_GET(self):
        clean_path = self.path.split("?")[0]
        # Route API endpoints through lambda handler
        if clean_path.startswith("/api/") or clean_path == "/routes":
            query_str = self.path.split("?")[1] if "?" in self.path else ""
            query_params = {}
            if query_str:
                import urllib.parse
                parsed = urllib.parse.parse_qs(query_str)
                query_params = {k: v[0] for k, v in parsed.items()}

            event = {
                "rawPath": clean_path,
                "path": clean_path,
                "queryStringParameters": query_params,
                "requestContext": {"http": {"method": "GET", "path": clean_path}}
            }
            resp = lambda_handler(event, None)
            self._send_lambda_response(resp)
        else:
            # Serve frontend files
            super().do_GET()

    def log_message(self, format, *args):
        print(f"[BreatheRoute DevServer] {args[0]} - {args[1]} {args[2]}")

def run_server(port=8000):
    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, UnifiedAppHandler)
    print(f"======================================================================")
    print(f"   Breathe Route & Canopy Unified Dev Server running on http://127.0.0.1:{port}")
    print(f"   Frontend UI:")
    print(f"     http://127.0.0.1:{port}/")
    print(f"   Endpoints:")
    print(f"     POST http://127.0.0.1:{port}/routes")
    print(f"     GET  http://127.0.0.1:{port}/api/overview")
    print(f"     POST http://127.0.0.1:{port}/api/recommend")
    print(f"     GET  http://127.0.0.1:{port}/api/health")
    print(f"======================================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping local server.")
        httpd.server_close()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    run_server(port)
