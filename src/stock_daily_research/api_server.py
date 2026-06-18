"""Simple HTTP API server for saving research state from daily report."""

import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

from .storage import init_db, import_research_state_payload

# Relative default kept as the documented DB location. Resolved against the
# project root at runtime so the server doesn't silently create a fresh empty
# DB when started from a different working directory.
DEFAULT_DB_PATH = Path("data/stock_daily.sqlite3")
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Reject oversized bodies before reading them into memory.
MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB

# Only same-machine origins may write. CORS response headers alone do NOT stop a
# cross-origin write (the request still reaches this handler), so the Origin is
# validated server-side and rejected before any DB mutation.
_ALLOWED_ORIGIN_HOSTS = ("localhost", "127.0.0.1")


def _resolved_db_path() -> Path:
    """Anchor the relative default DB path to the project root."""
    if DEFAULT_DB_PATH.is_absolute():
        return DEFAULT_DB_PATH
    return PROJECT_ROOT / DEFAULT_DB_PATH


def _origin_allowed(origin: str | None) -> bool:
    """Allow local report pages and non-browser clients; block remote sites.

    - Absent Origin: non-browser client (curl, tests) or same-origin -> allow.
    - "null": file:// page, which is how the report is normally opened -> allow.
    - localhost / 127.0.0.1 (any port): locally served report -> allow.
    - Anything else (a remote website doing a drive-by POST) -> deny.

    Matches on the parsed hostname, not a string prefix, so lookalikes such as
    "http://localhost.evil.com" are correctly rejected.
    """
    if not origin or origin == "null":
        return True
    parsed = urlparse(origin)
    return parsed.scheme in ("http", "https") and parsed.hostname in _ALLOWED_ORIGIN_HOSTS


def normalize_research_state_payload(data: dict) -> dict:
    """Accept either API wrapper or export JSON shape and return storage payload."""
    raw = data.get("research_state", data)
    if not isinstance(raw, dict):
        raise ValueError("research_state must be a JSON object")
    if "tickers" in raw:
        return raw
    return {
        "version": 1,
        "tickers": raw,
    }


class ResearchStateHandler(BaseHTTPRequestHandler):
    """HTTP request handler for research state API."""

    def _cors_origin(self) -> str:
        """Echo the request Origin when allowed (supports file:// 'null')."""
        origin = self.headers.get("Origin")
        if origin and _origin_allowed(origin):
            return origin
        return "null"

    def do_POST(self):
        """Handle POST requests to save research state."""
        parsed_path = urlparse(self.path)

        if parsed_path.path == "/api/save-research-state":
            self.handle_save_research_state()
        else:
            self.send_error(404, "Not Found")

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        origin = self.headers.get("Origin")
        if origin is not None and not _origin_allowed(origin):
            self.send_error(403, "Origin not allowed")
            return
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def handle_save_research_state(self):
        """Save research state from report to database."""
        try:
            # Block cross-origin writes up front, before reading/parsing the body.
            origin = self.headers.get("Origin")
            if origin is not None and not _origin_allowed(origin):
                self.send_error(403, "Origin not allowed")
                return

            # Read request body (guard against oversized payloads)
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > MAX_CONTENT_LENGTH:
                self.send_error(413, "Request body too large")
                return
            body = self.rfile.read(content_length).decode("utf-8")

            if not body:
                self.send_error(400, "Empty request body")
                return

            # Parse JSON payload
            try:
                data = json.loads(body)
            except json.JSONDecodeError as e:
                self.send_error(400, f"Invalid JSON: {e}")
                return

            try:
                research_state = normalize_research_state_payload(data)
            except ValueError as e:
                self.send_error(400, str(e))
                return

            # Connect to database and import
            try:
                conn = init_db(_resolved_db_path())
                import_research_state_payload(conn, research_state)
                conn.commit()
                conn.close()

                # Send success response
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", self._cors_origin())
                self.end_headers()

                response = {
                    "status": "success",
                    "message": f"Saved research state for {len(research_state.get('tickers', {}))} tickers"
                }
                self.wfile.write(json.dumps(response).encode("utf-8"))

            except Exception as e:
                self.send_error(500, f"Database error: {str(e)}")
                return

        except Exception as e:
            self.send_error(500, f"Server error: {str(e)}")
            return

    def log_message(self, format, *args):
        """Suppress default logging."""
        # Optionally log to file or custom handler
        print(f"[API] {format % args}")


def start_server(host: str = "127.0.0.1", port: int = 8765):
    """Start the API server."""
    server = HTTPServer((host, port), ResearchStateHandler)
    print(f"[OK] Research State API server started at http://{host}:{port}")
    print(f"     DB: {_resolved_db_path()}")
    print("     Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[STOP] Server stopped")
        server.server_close()
        sys.exit(0)


if __name__ == "__main__":
    start_server()
