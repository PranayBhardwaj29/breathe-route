"""
Zero-dependency HTTP client using Python's standard library (urllib.request).
Works seamlessly on any Python version (3.9 - 3.14) without requiring external C-extensions.
"""

import json
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional

class HttpResponse:
    def __init__(self, status_code: int, data: bytes):
        self.status_code = status_code
        self._data = data
        self.text = data.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)

def http_get(url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None, timeout: int = 8) -> HttpResponse:
    """Performs HTTP GET with optional query params and headers."""
    final_url = url
    if params:
        query_string = urllib.parse.urlencode(params)
        sep = "&" if "?" in final_url else "?"
        final_url = f"{final_url}{sep}{query_string}"

    req = urllib.request.Request(final_url)
    req.add_header("User-Agent", "BreatheRoute/1.0")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return HttpResponse(resp.status, resp.read())
    except urllib.error.HTTPError as e:
        return HttpResponse(e.code, e.read())

def http_post(url: str, json_data: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None, timeout: int = 8) -> HttpResponse:
    """Performs HTTP POST with JSON body."""
    body_bytes = json.dumps(json_data).encode("utf-8") if json_data is not None else b""
    req = urllib.request.Request(url, data=body_bytes, method="POST")
    req.add_header("User-Agent", "BreatheRoute/1.0")
    req.add_header("Content-Type", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return HttpResponse(resp.status, resp.read())
    except urllib.error.HTTPError as e:
        return HttpResponse(e.code, e.read())
