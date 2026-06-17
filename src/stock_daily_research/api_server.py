"""Simple HTTP API server for saving research state from daily report."""

import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

from .storage import init_db, import_research_state_payload

DEFAULT_DB_PATH = Path("data/stock_daily.sqlite3")


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

    def do_POST(self):
        """Handle POST requests to save research state."""
        parsed_path = urlparse(self.path)

        if parsed_path.path == "/api/save-research-state":
            self.handle_save_research_state()
        else:
            self.send_error(404, "Not Found")

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def handle_save_research_state(self):
        """Save research state from report to database."""
        try:
            # Read request body
            content_length = int(self.headers.get("Content-Length", 0))
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
                conn = init_db(DEFAULT_DB_PATH)
                import_research_state_payload(conn, research_state)
                conn.commit()
                conn.close()

                # Send success response
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
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
    print("     Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[STOP] Server stopped")
        server.server_close()
        sys.exit(0)


if __name__ == "__main__":
    start_server()
