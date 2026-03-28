# tests/test_auth_musickit.py
import json
import threading
import time
import urllib.request
from pathlib import Path


def test_save_user_token_appends_to_dotenv(tmp_path):
    """Token should be appended to .env file."""
    from auth_musickit import save_user_token
    dotenv = tmp_path / ".env"
    dotenv.write_text("LASTFM_API_KEY=abc\n")
    save_user_token("test-token-123", dotenv)
    content = dotenv.read_text()
    assert "APPLE_MUSIC_USER_TOKEN=test-token-123" in content
    assert "LASTFM_API_KEY=abc" in content


def test_save_user_token_replaces_existing(tmp_path):
    """If token already exists in .env, replace it."""
    from auth_musickit import save_user_token
    dotenv = tmp_path / ".env"
    dotenv.write_text("APPLE_MUSIC_USER_TOKEN=old-token\nOTHER=val\n")
    save_user_token("new-token-456", dotenv)
    content = dotenv.read_text()
    assert "APPLE_MUSIC_USER_TOKEN=new-token-456" in content
    assert "old-token" not in content
    assert "OTHER=val" in content


def test_auth_html_contains_musickit_setup():
    """The HTML file must load MusicKit JS and post token back."""
    html_path = Path(__file__).parent.parent / "auth_musickit.html"
    content = html_path.read_text()
    assert "MusicKit" in content
    assert "/callback" in content


def test_local_server_serves_html_and_callback():
    """Local server should serve the HTML page and accept token callback."""
    from auth_musickit import TokenServer
    server = TokenServer(port=0, developer_token="fake-dev-token")
    t = threading.Thread(target=server.serve_until_token, daemon=True)
    t.start()
    port = server.port
    resp = urllib.request.urlopen(f"http://localhost:{port}/")
    html = resp.read().decode()
    assert "MusicKit" in html
    assert "fake-dev-token" in html
    req = urllib.request.Request(
        f"http://localhost:{port}/callback",
        data=json.dumps({"token": "user-tok-abc"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req)
    time.sleep(0.2)
    assert server.user_token == "user-tok-abc"
