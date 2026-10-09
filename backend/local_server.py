"""
Local Development Server for Breathe Route.
Runs a lightweight HTTP server on port 8000 that routes requests directly
into backend/app.py lambda_handler, matching AWS Lambda Function URL behavior.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import sys
import os

# Add backend directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import lambda_handler

class BreatheRouteHandler(BaseHTTPRequestHandler):
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
            "requestContext": {"http": {"method": "OPTIONS"}}
        }
        resp = lambda_handler(event, None)
        self._send_lambda_response(resp)

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else ""
        
        event = {
            "requestContext": {"http": {"method": "POST"}},
            "body": raw_body
        }
        resp = lambda_handler(event, None)
        self._send_lambda_response(resp)

    def log_message(self, format, *args):
        print(f"[BreatheRoute DevServer] {args[0]} - {args[1]} {args[2]}")

def run_server(port=8000):
    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, BreatheRouteHandler)
    print(f"======================================================================")
    print(f"   Breathe Route Local Dev Server running on http://127.0.0.1:{port}")
    print(f"   Endpoints:")
    print(f"     POST http://127.0.0.1:{port}/routes")
    print(f"======================================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping local server.")
        httpd.server_close()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    run_server(port)
