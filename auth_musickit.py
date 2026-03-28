#!/usr/bin/env python3
"""
Music-User-Token acquisition for Apple Music API.

Serves a local page with MusicKit JS, attempts Playwright automation,
falls back to manual browser auth. Token is saved to .env.
"""

import http.server
import json
import logging
import pathlib
import threading
import time
import webbrowser

log = logging.getLogger("auth_musickit")

HTML_PATH = pathlib.Path(__file__).parent / "auth_musickit.html"
DEFAULT_PORT = 8374


def save_user_token(token, dotenv_path):
    """Save or replace APPLE_MUSIC_USER_TOKEN in .env file."""
    dotenv_path = pathlib.Path(dotenv_path)
    if dotenv_path.exists():
        lines = dotenv_path.read_text().splitlines()
        lines = [l for l in lines if not l.startswith("APPLE_MUSIC_USER_TOKEN=")]
    else:
        lines = []
    lines.append(f"APPLE_MUSIC_USER_TOKEN={token}")
    dotenv_path.write_text("\n".join(lines) + "\n")
    log.info(f"User token saved to {dotenv_path}")


class TokenServer:
    """Local HTTP server that serves MusicKit auth page and captures the token."""

    def __init__(self, port=DEFAULT_PORT, developer_token=""):
        self.developer_token = developer_token
        self.user_token = None
        self._html = HTML_PATH.read_text().replace("{{DEVELOPER_TOKEN}}", developer_token)
        self._server = http.server.HTTPServer(("127.0.0.1", port), self._make_handler())
        self.port = self._server.server_address[1]

    def _make_handler(self):
        server_ref = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(server_ref._html.encode())

            def do_POST(self):
                if self.path == "/callback":
                    length = int(self.headers.get("Content-Length", 0))
                    try:
                        body = json.loads(self.rfile.read(length))
                        server_ref.user_token = body.get("token")
                        self.send_response(200)
                    except (json.JSONDecodeError, ValueError):
                        self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"ok")
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                pass  # suppress default HTTP logging

        return Handler

    def serve_until_token(self, timeout=300):
        """Serve until token is received or timeout (seconds)."""
        self._server.timeout = 1
        deadline = time.monotonic() + timeout
        while self.user_token is None and time.monotonic() < deadline:
            self._server.handle_request()
        self._server.server_close()


def acquire_user_token(developer_token, dotenv_path, port=DEFAULT_PORT):
    """Acquire a Music-User-Token. Tries Playwright automation, falls back to manual.

    Returns the token string, or None on failure.
    """
    server = TokenServer(port=port, developer_token=developer_token)
    url = f"http://localhost:{server.port}/"

    # Start server in background
    server_thread = threading.Thread(target=server.serve_until_token, daemon=True)
    server_thread.start()

    # Try Playwright automation (token arrives via server callback)
    _try_playwright_auth(url)
    if server.user_token:
        save_user_token(server.user_token, dotenv_path)
        return server.user_token

    # Fallback: open browser for manual auth
    log.info(f"Opening browser for Apple Music authorization: {url}")
    log.info("Click 'Connect to Apple Music' and sign in with your Apple ID.")
    webbrowser.open(url)

    server_thread.join(timeout=300)
    if server.user_token:
        save_user_token(server.user_token, dotenv_path)
        return server.user_token

    log.error("Timed out waiting for Apple Music authorization.")
    return None


def _try_playwright_auth(url):
    """Attempt to automate MusicKit auth via Playwright. Returns token or None."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.info("Playwright not installed — skipping automated auth.")
        return None

    log.info("Attempting automated Apple Music authorization via Playwright...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            page.goto(url)

            # Click the authorize button
            page.click("#auth-btn")

            # Wait for the success message (Apple sign-in popup handled by user)
            page.wait_for_selector(".success", timeout=120000)

            # Token was posted to our server by this point
            browser.close()
            return None  # token comes via the server callback, not from here
    except Exception as e:
        log.info(f"Playwright automation failed: {e}. Falling back to manual auth.")
        return None
