# Signal Wargaming Tool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only evaluation tool that collects all available preference signals from the user's Apple Music library and API, analyzes each signal's impact on discovery rankings, and recommends weight configurations validated by listening.

**Architecture:** Single script `signal_experiment.py` that imports existing infrastructure (`_run_jxa`, `AppleMusicClient`, `load_cache`, etc.) and adds new data collectors, a multi-signal scoring function, and a four-phase analysis engine. A companion `auth_musickit.py` module handles Music-User-Token acquisition. All data is cached to JSON; no mutation of library or playlists until the explicit playlist-build step.

**Tech Stack:** Python 3, JXA via osascript, Apple Music API (REST), Playwright (for MusicKit JS auth), existing `music_discovery.py` and `compare_similarity.py` imports.

---

### Task 1: Music-User-Token Auth Module

**Files:**
- Create: `auth_musickit.py`
- Create: `auth_musickit.html`
- Create: `tests/test_auth_musickit.py`

This module serves a minimal local HTML page with MusicKit JS, attempts Playwright automation of the Apple sign-in, and falls back to asking the user to click manually. The token is appended to `.env`.

- [ ] **Step 1: Write failing tests for token storage and HTML serving**

```python
# tests/test_auth_musickit.py
import json
import threading
import time
import urllib.request
import pytest
from unittest.mock import patch, MagicMock
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
    # Fetch the HTML page
    resp = urllib.request.urlopen(f"http://localhost:{port}/")
    html = resp.read().decode()
    assert "MusicKit" in html
    assert "fake-dev-token" in html
    # Post a fake token via callback
    req = urllib.request.Request(
        f"http://localhost:{port}/callback",
        data=json.dumps({"token": "user-tok-abc"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req)
    time.sleep(0.2)
    assert server.user_token == "user-tok-abc"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_auth_musickit.py -v`
Expected: FAIL — `auth_musickit` module not found.

- [ ] **Step 3: Create the MusicKit HTML page**

```html
<!-- auth_musickit.html -->
<!DOCTYPE html>
<html>
<head>
    <title>Music Discovery — Apple Music Authorization</title>
    <style>
        body { font-family: -apple-system, sans-serif; max-width: 500px; margin: 80px auto; text-align: center; }
        button { font-size: 18px; padding: 12px 32px; cursor: pointer; border-radius: 8px; border: none; background: #fa243c; color: white; }
        button:hover { background: #d91e34; }
        #status { margin-top: 20px; color: #666; }
        .success { color: #28a745 !important; font-weight: bold; }
        .error { color: #dc3545 !important; }
    </style>
</head>
<body>
    <h1>Apple Music Authorization</h1>
    <p>Click below to connect your Apple Music account.<br>This grants read-only access to your listening history.</p>
    <button id="auth-btn" onclick="authorize()">Connect to Apple Music</button>
    <div id="status"></div>

    <script src="https://js-cdn.music.apple.com/musickit/v3/musickit.js"
            data-web-components
            crossorigin></script>
    <script>
        const DEVELOPER_TOKEN = "{{DEVELOPER_TOKEN}}";
        let music;

        document.addEventListener("musickitloaded", async () => {
            music = await MusicKit.configure({
                developerToken: DEVELOPER_TOKEN,
                app: { name: "Music Discovery", build: "1.0" },
            });
        });

        async function authorize() {
            const status = document.getElementById("status");
            const btn = document.getElementById("auth-btn");
            try {
                btn.disabled = true;
                status.textContent = "Waiting for Apple Music authorization...";
                const token = await music.authorize();
                status.textContent = "Sending token...";
                const resp = await fetch("/callback", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({token: token}),
                });
                if (resp.ok) {
                    status.textContent = "Authorization complete! You can close this tab.";
                    status.className = "success";
                } else {
                    throw new Error("Server rejected the token");
                }
            } catch (e) {
                status.textContent = "Authorization failed: " + e.message;
                status.className = "error";
                btn.disabled = false;
            }
        }
    </script>
</body>
</html>
```

- [ ] **Step 4: Implement auth_musickit.py**

```python
#!/usr/bin/env python3
"""
Music-User-Token acquisition for Apple Music API.

Serves a local page with MusicKit JS, attempts Playwright automation,
falls back to manual browser auth. Token is saved to .env.
"""

import http.server
import json
import logging
import os
import pathlib
import re
import threading
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
                    body = json.loads(self.rfile.read(length))
                    server_ref.user_token = body.get("token")
                    self.send_response(200)
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
        elapsed = 0
        while self.user_token is None and elapsed < timeout:
            self._server.handle_request()
            elapsed += 1
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_auth_musickit.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add auth_musickit.py auth_musickit.html tests/test_auth_musickit.py
git commit -m "feat: add MusicKit user-token auth module with Playwright automation and manual fallback"
```

---

### Task 2: JXA Data Collectors — Play Counts and Playlist Membership

**Files:**
- Create: `signal_collectors.py`
- Create: `tests/test_signal_collectors.py`

New JXA-based collectors for play count and playlist membership signals. Separated into their own module to keep `signal_experiment.py` focused on analysis.

- [ ] **Step 1: Write failing tests for play count collector**

```python
# tests/test_signal_collectors.py
import json
import pytest
from unittest.mock import patch, MagicMock


def test_collect_playcounts_aggregates_by_artist():
    """Play counts should sum across all tracks per artist (lowercase)."""
    from signal_collectors import collect_playcounts_jxa
    fake_output = json.dumps([
        {"artist": "Haken", "playCount": 50},
        {"artist": "Haken", "playCount": 30},
        {"artist": "Tool", "playCount": 10},
        {"artist": "tool", "playCount": 5},
    ])
    with patch("signal_collectors._run_jxa", return_value=(fake_output, 0)):
        result = collect_playcounts_jxa()
    assert result == {"haken": 80, "tool": 15}


def test_collect_playcounts_skips_zero_plays():
    """Artists with zero total plays should not appear."""
    from signal_collectors import collect_playcounts_jxa
    fake_output = json.dumps([
        {"artist": "Haken", "playCount": 10},
        {"artist": "Silence", "playCount": 0},
    ])
    with patch("signal_collectors._run_jxa", return_value=(fake_output, 0)):
        result = collect_playcounts_jxa()
    assert result == {"haken": 10}
    assert "silence" not in result


def test_collect_playcounts_handles_empty_artist():
    """Tracks with empty/missing artist should be skipped."""
    from signal_collectors import collect_playcounts_jxa
    fake_output = json.dumps([
        {"artist": "", "playCount": 5},
        {"artist": "Haken", "playCount": 10},
    ])
    with patch("signal_collectors._run_jxa", return_value=(fake_output, 0)):
        result = collect_playcounts_jxa()
    assert result == {"haken": 10}


def test_collect_playcounts_jxa_failure():
    """Should raise RuntimeError on JXA failure."""
    from signal_collectors import collect_playcounts_jxa
    with patch("signal_collectors._run_jxa", return_value=("error", 1)):
        with pytest.raises(RuntimeError, match="JXA play count read failed"):
            collect_playcounts_jxa()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_collectors.py::test_collect_playcounts_aggregates_by_artist -v`
Expected: FAIL — `signal_collectors` module not found.

- [ ] **Step 3: Implement play count collector**

```python
# signal_collectors.py
"""
Signal collectors for the wargaming experiment.

JXA-based collectors for play counts and playlist membership,
plus Apple Music API collectors for heavy rotation and recommendations.
"""

import json
import logging
import math
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from music_discovery import _run_jxa

log = logging.getLogger("signal_collectors")


def collect_playcounts_jxa():
    """Read play counts for ALL library tracks via JXA.

    Returns {artist_lowercase: total_play_count} for artists with plays > 0.
    Raises RuntimeError on JXA failure.
    """
    script = '''
var music = Application("Music");
var lib = music.libraryPlaylists[0];
var tracks = lib.tracks;
var count = tracks.length;
var result = [];
if (count > 0) {
    var artists = tracks.artist();
    var playCounts = tracks.playedCount();
    for (var i = 0; i < count; i++) {
        result.push({artist: artists[i] || "", playCount: playCounts[i] || 0});
    }
}
JSON.stringify(result);
'''
    stdout, code = _run_jxa(script)
    if code != 0:
        raise RuntimeError(f"JXA play count read failed (exit {code}): {stdout}")
    try:
        tracks = json.loads(stdout)
    except (json.JSONDecodeError, TypeError) as e:
        raise RuntimeError(f"Failed to parse JXA play count output: {e}")

    counts = {}
    for t in tracks:
        artist = t.get("artist", "")
        if not isinstance(artist, str):
            continue
        artist = artist.strip().lower()
        if not artist:
            continue
        pc = t.get("playCount", 0) or 0
        counts[artist] = counts.get(artist, 0) + pc

    # Remove artists with zero total plays
    return {a: c for a, c in counts.items() if c > 0}
```

- [ ] **Step 4: Run play count tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_collectors.py -k playcount -v`
Expected: All 4 playcount tests PASS.

- [ ] **Step 5: Write failing tests for playlist membership collector**

Add to `tests/test_signal_collectors.py`:

```python
def test_collect_playlists_counts_membership():
    """Should count how many user playlists each artist appears in."""
    from signal_collectors import collect_user_playlists_jxa
    fake_output = json.dumps([
        {"name": "Chill Vibes", "tracks": [
            {"artist": "Haken"}, {"artist": "Tool"}, {"artist": "Haken"}
        ]},
        {"name": "Workout", "tracks": [
            {"artist": "Tool"}, {"artist": "Meshuggah"}
        ]},
    ])
    with patch("signal_collectors._run_jxa", return_value=(fake_output, 0)):
        result = collect_user_playlists_jxa()
    # Haken in 1 playlist (deduplicated within), Tool in 2, Meshuggah in 1
    assert result == {"haken": 1, "tool": 2, "meshuggah": 1}


def test_collect_playlists_skips_smart_and_apple_playlists():
    """Smart playlists and Apple-curated playlists should be excluded."""
    from signal_collectors import collect_user_playlists_jxa
    # JXA script only reads non-smart, non-special playlists
    fake_output = json.dumps([
        {"name": "My Mix", "tracks": [{"artist": "Haken"}]},
    ])
    with patch("signal_collectors._run_jxa", return_value=(fake_output, 0)):
        result = collect_user_playlists_jxa()
    assert result == {"haken": 1}


def test_collect_playlists_excludes_music_discovery():
    """The 'Music Discovery' playlist should be excluded (it's our output).
    Note: JXA script handles this exclusion, but we add Python-side filtering
    as defense-in-depth since tests mock _run_jxa."""
    from signal_collectors import collect_user_playlists_jxa
    fake_output = json.dumps([
        {"name": "My Mix", "tracks": [{"artist": "Haken"}]},
        {"name": "Music Discovery", "tracks": [{"artist": "Tool"}, {"artist": "Meshuggah"}]},
    ])
    with patch("signal_collectors._run_jxa", return_value=(fake_output, 0)):
        result = collect_user_playlists_jxa()
    assert result == {"haken": 1}
    assert "tool" not in result
    assert "meshuggah" not in result


def test_collect_playlists_jxa_failure():
    """Should raise RuntimeError on JXA failure."""
    from signal_collectors import collect_user_playlists_jxa
    with patch("signal_collectors._run_jxa", return_value=("error", 1)):
        with pytest.raises(RuntimeError, match="JXA playlist read failed"):
            collect_user_playlists_jxa()
```

- [ ] **Step 6: Run playlist tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_collectors.py -k playlist -v`
Expected: FAIL — `collect_user_playlists_jxa` not found.

- [ ] **Step 7: Implement playlist membership collector**

Add to `signal_collectors.py`:

```python
def collect_user_playlists_jxa():
    """Read all user-created playlists and count artist membership.

    Excludes smart playlists, Apple-curated playlists, and the
    'Music Discovery' playlist (our own output).

    Returns {artist_lowercase: playlist_count} where playlist_count is
    the number of distinct user playlists the artist appears in.
    Raises RuntimeError on JXA failure.
    """
    script = '''
var music = Application("Music");
var playlists = music.userPlaylists();
var result = [];
for (var i = 0; i < playlists.length; i++) {
    var pl = playlists[i];
    try {
        if (pl.smart()) continue;
    } catch(e) {}
    var name = pl.name();
    if (name === "Music Discovery") continue;
    var tracks = pl.tracks;
    var count = tracks.length;
    if (count === 0) continue;
    var artists = tracks.artist();
    var trackList = [];
    for (var j = 0; j < count; j++) {
        trackList.push({artist: artists[j] || ""});
    }
    result.push({name: name, tracks: trackList});
}
JSON.stringify(result);
'''
    stdout, code = _run_jxa(script)
    if code != 0:
        raise RuntimeError(f"JXA playlist read failed (exit {code}): {stdout}")
    try:
        playlists = json.loads(stdout)
    except (json.JSONDecodeError, TypeError) as e:
        raise RuntimeError(f"Failed to parse JXA playlist output: {e}")

    counts = {}
    for pl in playlists:
        # Skip Music Discovery playlist (defense-in-depth, JXA also filters)
        if pl.get("name") == "Music Discovery":
            continue
        # Deduplicate artists within a single playlist
        artists_in_pl = set()
        for t in pl.get("tracks", []):
            artist = t.get("artist", "")
            if not isinstance(artist, str):
                continue
            artist = artist.strip().lower()
            if artist:
                artists_in_pl.add(artist)
        for artist in artists_in_pl:
            counts[artist] = counts.get(artist, 0) + 1

    return counts
```

- [ ] **Step 8: Run all collector tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_collectors.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 9: Commit**

```bash
git add signal_collectors.py tests/test_signal_collectors.py
git commit -m "feat: add JXA collectors for play counts and playlist membership"
```

---

### Task 3: API Data Collectors — Heavy Rotation and Recommendations

**Files:**
- Modify: `signal_collectors.py`
- Modify: `tests/test_signal_collectors.py`

Add collectors that use the Music-User-Token to fetch heavy rotation and personal recommendation data from the Apple Music API.

- [ ] **Step 1: Write failing tests for heavy rotation collector**

Add to `tests/test_signal_collectors.py`:

```python
def test_collect_heavy_rotation_extracts_artists():
    """Should extract artist names from heavy rotation albums."""
    from signal_collectors import collect_heavy_rotation
    fake_response = {
        "data": [
            {"type": "albums", "attributes": {"artistName": "Haken"}},
            {"type": "albums", "attributes": {"artistName": "Tool"}},
            {"type": "playlists", "attributes": {"name": "Chill Vibes"}},
            {"type": "albums", "attributes": {"artistName": "Haken"}},
        ]
    }
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = fake_response
    mock_resp.raise_for_status = MagicMock()
    mock_session.get.return_value = mock_resp

    result = collect_heavy_rotation(mock_session)
    assert result == {"haken", "tool"}


def test_collect_heavy_rotation_empty():
    """Should return empty set when no heavy rotation data."""
    from signal_collectors import collect_heavy_rotation
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": []}
    mock_resp.raise_for_status = MagicMock()
    mock_session.get.return_value = mock_resp

    result = collect_heavy_rotation(mock_session)
    assert result == set()


def test_collect_recommendations_extracts_artists():
    """Should extract artist names from recommended albums."""
    from signal_collectors import collect_recommendations
    fake_response = {
        "data": [
            {"relationships": {"contents": {"data": [
                {"type": "albums", "attributes": {"artistName": "Meshuggah"}},
                {"type": "albums", "attributes": {"artistName": "Gojira"}},
            ]}}},
            {"relationships": {"contents": {"data": [
                {"type": "playlists", "attributes": {"name": "New Music Mix"}},
                {"type": "albums", "attributes": {"artistName": "Meshuggah"}},
            ]}}},
        ]
    }
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = fake_response
    mock_resp.raise_for_status = MagicMock()
    mock_session.get.return_value = mock_resp

    result = collect_recommendations(mock_session)
    assert result == {"meshuggah", "gojira"}


def test_collect_recommendations_empty():
    """Should return empty set when no recommendations."""
    from signal_collectors import collect_recommendations
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": []}
    mock_resp.raise_for_status = MagicMock()
    mock_session.get.return_value = mock_resp

    result = collect_recommendations(mock_session)
    assert result == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_collectors.py -k "heavy_rotation or recommendation" -v`
Expected: FAIL — functions not found.

- [ ] **Step 3: Implement API collectors**

Add to `signal_collectors.py`:

```python
APPLE_MUSIC_API_BASE = "https://api.music.apple.com/v1/me"


def _make_user_session(developer_token, user_token):
    """Create a requests.Session with both developer and user tokens."""
    import requests
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {developer_token}",
        "Music-User-Token": user_token,
        "Content-Type": "application/json",
    })
    return session


def collect_heavy_rotation(session):
    """Fetch heavy rotation content from Apple Music API.

    Args:
        session: requests.Session with Authorization and Music-User-Token headers.

    Returns:
        set of lowercase artist names from heavy rotation albums.
    """
    url = f"{APPLE_MUSIC_API_BASE}/history/heavy-rotation"
    try:
        resp = session.get(url, params={"limit": 25}, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        log.warning(f"Heavy rotation fetch failed: {e}")
        return set()

    artists = set()
    for item in resp.json().get("data", []):
        if item.get("type") in ("albums", "library-albums"):
            name = item.get("attributes", {}).get("artistName", "")
            if name:
                artists.add(name.strip().lower())
    return artists


def collect_recommendations(session):
    """Fetch personal recommendations from Apple Music API.

    Args:
        session: requests.Session with Authorization and Music-User-Token headers.

    Returns:
        set of lowercase artist names from recommended content.
    """
    url = f"{APPLE_MUSIC_API_BASE}/recommendations"
    try:
        resp = session.get(url, params={"limit": 25}, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        log.warning(f"Recommendations fetch failed: {e}")
        return set()

    artists = set()
    for rec in resp.json().get("data", []):
        contents = rec.get("relationships", {}).get("contents", {}).get("data", [])
        for item in contents:
            if item.get("type") in ("albums", "library-albums"):
                name = item.get("attributes", {}).get("artistName", "")
                if name:
                    artists.add(name.strip().lower())
    return artists
```

- [ ] **Step 4: Run API collector tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_collectors.py -k "heavy_rotation or recommendation" -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add signal_collectors.py tests/test_signal_collectors.py
git commit -m "feat: add API collectors for heavy rotation and personal recommendations"
```

---

### Task 4: Multi-Signal Scoring Function

**Files:**
- Create: `signal_scoring.py`
- Create: `tests/test_signal_scoring.py`

The core scoring function that replaces the single-signal `score_artists()` with a multi-signal version accepting per-signal weights.

- [ ] **Step 1: Write failing tests for signal value computation**

```python
# tests/test_signal_scoring.py
import math
import pytest


def test_compute_signal_value_logarithmic():
    """Continuous signals should use sqrt(log(x+1)) scaling."""
    from signal_scoring import compute_signal_value
    # log(11) ≈ 2.397, sqrt(2.397) ≈ 1.548
    result = compute_signal_value(10)
    assert abs(result - math.sqrt(math.log(11))) < 0.001


def test_compute_signal_value_zero():
    """Zero input should return zero signal value."""
    from signal_scoring import compute_signal_value
    assert compute_signal_value(0) == 0.0


def test_compute_signal_value_capped():
    """When cap is specified, values above cap should be clamped before scaling."""
    from signal_scoring import compute_signal_value
    capped = compute_signal_value(100, cap=5)
    uncapped_at_5 = compute_signal_value(5)
    assert abs(capped - uncapped_at_5) < 0.001


def test_compute_seed_weight_single_signal():
    """With only favorites on, should match existing behavior."""
    from signal_scoring import compute_seed_weight
    weights = {"favorites": 1.0, "playcount": 0.0, "playlists": 0.0,
               "heavy_rotation": 0.0, "recommendations": 0.0}
    signals = {
        "favorites": {"haken": 5},
        "playcount": {"haken": 100},
        "playlists": {"haken": 3},
        "heavy_rotation": {"haken"},
        "recommendations": set(),
    }
    result = compute_seed_weight("haken", signals, weights)
    expected = 1.0 * math.sqrt(math.log(6))
    assert abs(result - expected) < 0.001


def test_compute_seed_weight_multi_signal():
    """Multiple signals should combine additively."""
    from signal_scoring import compute_seed_weight
    weights = {"favorites": 1.0, "playcount": 0.3, "playlists": 0.0,
               "heavy_rotation": 0.0, "recommendations": 0.0}
    signals = {
        "favorites": {"haken": 5},
        "playcount": {"haken": 100},
        "playlists": {},
        "heavy_rotation": set(),
        "recommendations": set(),
    }
    result = compute_seed_weight("haken", signals, weights)
    fav_part = 1.0 * math.sqrt(math.log(6))
    pc_part = 0.3 * math.sqrt(math.log(101))
    assert abs(result - (fav_part + pc_part)) < 0.001


def test_compute_seed_weight_binary_signal():
    """Binary signals (heavy rotation, recs) should add flat bonus."""
    from signal_scoring import compute_seed_weight
    weights = {"favorites": 0.0, "playcount": 0.0, "playlists": 0.0,
               "heavy_rotation": 0.5, "recommendations": 0.0}
    signals = {
        "favorites": {},
        "playcount": {},
        "playlists": {},
        "heavy_rotation": {"haken"},
        "recommendations": set(),
    }
    result = compute_seed_weight("haken", signals, weights)
    assert abs(result - 0.5) < 0.001


def test_compute_seed_weight_not_in_binary_signal():
    """Artist NOT in binary signal set should get zero for that signal."""
    from signal_scoring import compute_seed_weight
    weights = {"favorites": 0.0, "playcount": 0.0, "playlists": 0.0,
               "heavy_rotation": 0.5, "recommendations": 0.0}
    signals = {
        "favorites": {},
        "playcount": {},
        "playlists": {},
        "heavy_rotation": {"tool"},
        "recommendations": set(),
    }
    result = compute_seed_weight("haken", signals, weights)
    assert result == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_scoring.py -v`
Expected: FAIL — `signal_scoring` module not found.

- [ ] **Step 3: Implement signal value computation and seed weight**

```python
# signal_scoring.py
"""
Multi-signal scoring for the wargaming experiment.

Computes composite seed weights from multiple preference signals
and scores candidates using the weighted similarity formula.
"""

import math
import logging

log = logging.getLogger("signal_scoring")

# Which signals are continuous (dict-valued) vs binary (set-valued)
CONTINUOUS_SIGNALS = ("favorites", "playcount", "playlists")
BINARY_SIGNALS = ("heavy_rotation", "recommendations")
ALL_SIGNALS = CONTINUOUS_SIGNALS + BINARY_SIGNALS
DEFAULT_WEIGHTS = {s: 0.0 for s in ALL_SIGNALS}


def compute_signal_value(raw_count, cap=None):
    """Compute logarithmically scaled signal value.

    Formula: sqrt(log(min(raw_count, cap) + 1))
    Returns 0.0 for zero input.
    """
    if raw_count <= 0:
        return 0.0
    if cap is not None and raw_count > cap:
        raw_count = cap
    return math.sqrt(math.log(raw_count + 1))


def compute_seed_weight(artist, signals, weights, caps=None):
    """Compute composite seed weight for a library artist.

    Args:
        artist: lowercase artist name.
        signals: dict with keys matching ALL_SIGNALS.
            Continuous signals: {artist: count} dicts.
            Binary signals: set of artist names.
        weights: {signal_name: float} coefficient per signal.
        caps: optional {signal_name: int} caps for continuous signals.

    Returns:
        float seed weight (can be 0.0 if artist has no signal data).
    """
    if caps is None:
        caps = {}
    total = 0.0
    for sig in CONTINUOUS_SIGNALS:
        w = weights.get(sig, 0.0)
        if w == 0.0:
            continue
        raw = signals.get(sig, {}).get(artist, 0)
        total += w * compute_signal_value(raw, cap=caps.get(sig))
    for sig in BINARY_SIGNALS:
        w = weights.get(sig, 0.0)
        if w == 0.0:
            continue
        if artist in signals.get(sig, set()):
            total += w
    return total
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_scoring.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 5: Write failing tests for multi-signal candidate scoring**

Add to `tests/test_signal_scoring.py`:

```python
def test_score_candidates_multisignal_basic():
    """Should score candidates using composite seed weights."""
    from signal_scoring import score_candidates_multisignal
    cache = {
        "haken": {"umpfel": 0.9, "native construct": 0.8},
        "tool": {"umpfel": 0.7, "meshuggah": 0.6},
    }
    signals = {
        "favorites": {"haken": 5, "tool": 2},
        "playcount": {"haken": 100, "tool": 50},
        "playlists": {},
        "heavy_rotation": set(),
        "recommendations": set(),
    }
    weights = {"favorites": 1.0, "playcount": 0.3, "playlists": 0.0,
               "heavy_rotation": 0.0, "recommendations": 0.0}
    ranked = score_candidates_multisignal(cache, signals, weights)
    names = [name for _, name in ranked]
    assert "umpfel" in names
    assert "haken" not in names  # library artists excluded
    assert "tool" not in names


def test_score_candidates_multisignal_excludes_blocklist():
    """User blocklist artists should be excluded from results."""
    from signal_scoring import score_candidates_multisignal
    cache = {"haken": {"umpfel": 0.9, "bad artist": 0.8}}
    signals = {
        "favorites": {"haken": 5},
        "playcount": {},
        "playlists": {},
        "heavy_rotation": set(),
        "recommendations": set(),
    }
    weights = {"favorites": 1.0, "playcount": 0.0, "playlists": 0.0,
               "heavy_rotation": 0.0, "recommendations": 0.0}
    ranked = score_candidates_multisignal(
        cache, signals, weights, user_blocklist={"bad artist"})
    names = [name for _, name in ranked]
    assert "umpfel" in names
    assert "bad artist" not in names


def test_score_candidates_multisignal_with_negative_scoring():
    """Rejected artist similarity should reduce scores."""
    from signal_scoring import score_candidates_multisignal
    cache = {"haken": {"umpfel": 0.9, "pop artist": 0.5}}
    blocklist_cache = {"reo speedwagon": {"pop artist": 0.8}}
    signals = {
        "favorites": {"haken": 5},
        "playcount": {},
        "playlists": {},
        "heavy_rotation": set(),
        "recommendations": set(),
    }
    weights = {"favorites": 1.0, "playcount": 0.0, "playlists": 0.0,
               "heavy_rotation": 0.0, "recommendations": 0.0}
    ranked = score_candidates_multisignal(
        cache, signals, weights, blocklist_cache=blocklist_cache, neg_penalty=0.4)
    scores = {name: score for score, name in ranked}
    # pop artist should have reduced score due to negative scoring
    assert scores["umpfel"] > scores["pop artist"]


def test_score_candidates_zero_weight_artist_excluded():
    """Artists with zero composite seed weight should not contribute."""
    from signal_scoring import score_candidates_multisignal
    cache = {
        "haken": {"umpfel": 0.9},
        "unknown": {"other": 0.9},
    }
    signals = {
        "favorites": {"haken": 5},
        "playcount": {},
        "playlists": {},
        "heavy_rotation": set(),
        "recommendations": set(),
    }
    # Only favorites on, "unknown" has no favorites → zero weight
    weights = {"favorites": 1.0, "playcount": 0.0, "playlists": 0.0,
               "heavy_rotation": 0.0, "recommendations": 0.0}
    ranked = score_candidates_multisignal(cache, signals, weights)
    names = [name for _, name in ranked]
    scores = {name: score for score, name in ranked}
    assert "umpfel" in names
    # "unknown" has 0 seed weight, so "other" gets 0 contribution
    assert scores.get("other", 0.0) == 0.0
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_scoring.py -k "score_candidates" -v`
Expected: FAIL — `score_candidates_multisignal` not found.

- [ ] **Step 7: Implement multi-signal candidate scoring**

Add to `signal_scoring.py`:

```python
NEGATIVE_PENALTY = 0.4  # default, matches existing music_discovery.py


def score_candidates_multisignal(cache, signals, weights, *,
                                  apple_cache=None, apple_weight=0.2,
                                  blocklist_cache=None, neg_penalty=NEGATIVE_PENALTY,
                                  user_blocklist=None, caps=None):
    """Score candidates using multi-signal seed weights.

    Positive (music-map):
        score(C) += seed_weight(L) * proximity(L, C)

    Positive (Apple Music, add-if-absent):
        score(C) += apple_weight  (flat, only if C not in music-map for that seed)

    Negative (rejected discovery artists):
        score(C) -= neg_penalty * proximity(B, C)

    Args:
        cache: {artist: {similar: proximity}} from music-map scrape.
        signals: dict of signal data (see compute_seed_weight).
        weights: {signal_name: float} per-signal coefficients.
        apple_cache: {artist: [similar_artists]} from Apple Music API. None to skip.
        apple_weight: flat bonus for Apple-only candidates.
        blocklist_cache: {artist: {similar: proximity}} for rejected artists. None to skip.
        neg_penalty: penalty multiplier for negative scoring.
        user_blocklist: set of lowercase artist names to exclude.
        caps: optional {signal_name: int} caps for continuous signals.

    Returns:
        List of (score, artist_name) sorted descending.
    """
    if apple_cache is None:
        apple_cache = {}
    if blocklist_cache is None:
        blocklist_cache = {}
    if user_blocklist is None:
        user_blocklist = set()

    # All artists that appear in any signal are potential library artists
    library_set = set(cache.keys())
    exclude = library_set | user_blocklist
    scores = {}

    # Positive scoring from music-map
    for lib_artist, similar in cache.items():
        if not isinstance(similar, dict):
            continue
        weight = compute_seed_weight(lib_artist, signals, weights, caps=caps)
        if weight <= 0:
            continue
        for candidate, proximity in similar.items():
            if candidate not in exclude:
                scores[candidate] = scores.get(candidate, 0.0) + weight * proximity

    # Positive scoring from Apple Music (add-if-absent)
    if apple_weight > 0:
        for lib_artist, apple_similar in apple_cache.items():
            if lib_artist not in library_set:
                continue
            weight = compute_seed_weight(lib_artist, signals, weights, caps=caps)
            if weight <= 0:
                continue
            musicmap_similar = cache.get(lib_artist, {})
            for candidate in apple_similar:
                candidate_lower = candidate.lower()
                if candidate_lower not in exclude and candidate_lower not in musicmap_similar:
                    scores[candidate_lower] = scores.get(candidate_lower, 0.0) + apple_weight

    # Negative scoring from rejected discovery artists
    if neg_penalty > 0:
        for bl_artist, similar in blocklist_cache.items():
            if not isinstance(similar, dict):
                continue
            for candidate, proximity in similar.items():
                if candidate not in exclude:
                    scores[candidate] = scores.get(candidate, 0.0) - neg_penalty * proximity

    return sorted(((v, k) for k, v in scores.items()),
                  key=lambda x: x[0], reverse=True)
```

- [ ] **Step 8: Run all scoring tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_scoring.py -v`
Expected: All 12 tests PASS.

- [ ] **Step 9: Commit**

```bash
git add signal_scoring.py tests/test_signal_scoring.py
git commit -m "feat: add multi-signal scoring with composite seed weights and logarithmic scaling"
```

---

### Task 5: Analysis Phases A & B — Signal Profiling and Ablation

**Files:**
- Create: `signal_analysis.py`
- Create: `tests/test_signal_analysis.py`

The analysis engine that runs individual signal profiles and ablation studies.

- [ ] **Step 1: Write failing tests for Phase A**

```python
# tests/test_signal_analysis.py
import pytest


def _make_test_data():
    """Shared test fixtures for analysis tests."""
    cache = {
        "haken": {"umpfel": 0.9, "native construct": 0.8, "pop artist": 0.3},
        "tool": {"umpfel": 0.7, "meshuggah": 0.6, "pop artist": 0.5},
        "adele": {"pop artist": 0.9, "ed sheeran": 0.8},
    }
    signals = {
        "favorites": {"haken": 5, "tool": 2},
        "playcount": {"haken": 100, "tool": 50, "adele": 200},
        "playlists": {"haken": 3, "adele": 5},
        "heavy_rotation": {"adele", "tool"},
        "recommendations": {"haken", "meshuggah"},
    }
    return cache, signals


def test_phase_a_produces_per_signal_results():
    """Phase A should produce one result set per signal."""
    from signal_analysis import run_phase_a
    cache, signals = _make_test_data()
    results = run_phase_a(cache, signals, top_n=10)
    assert set(results.keys()) == {"favorites", "playcount", "playlists",
                                    "heavy_rotation", "recommendations"}
    for signal_name, data in results.items():
        assert "ranked" in data
        assert "unique" in data
        assert "baseline_overlap" in data


def test_phase_a_favorites_only_matches_baseline():
    """Favorites-only signal should have 100% overlap with itself as baseline."""
    from signal_analysis import run_phase_a
    cache, signals = _make_test_data()
    results = run_phase_a(cache, signals, top_n=10)
    assert results["favorites"]["baseline_overlap"] == 100.0


def test_phase_a_unique_artists_are_exclusive():
    """Unique artists for a signal should not appear in any other signal's top N."""
    from signal_analysis import run_phase_a
    cache, signals = _make_test_data()
    results = run_phase_a(cache, signals, top_n=10)
    for sig, data in results.items():
        other_artists = set()
        for other_sig, other_data in results.items():
            if other_sig != sig:
                other_artists.update(name for _, name in other_data["ranked"][:10])
        for artist in data["unique"]:
            assert artist not in other_artists


def test_phase_b_produces_per_signal_ablation():
    """Phase B should produce one ablation result per signal."""
    from signal_analysis import run_phase_b
    cache, signals = _make_test_data()
    results = run_phase_b(cache, signals, top_n=10)
    assert set(results.keys()) == {"favorites", "playcount", "playlists",
                                    "heavy_rotation", "recommendations"}
    for signal_name, data in results.items():
        assert "dropped" in data
        assert "entered" in data
        assert "ranked" in data


def test_phase_b_dropping_signal_changes_results():
    """Dropping a signal that contributes should change the ranking."""
    from signal_analysis import run_phase_b
    cache, signals = _make_test_data()
    results = run_phase_b(cache, signals, top_n=10)
    # At least one signal's ablation should show changes
    any_changes = any(
        len(data["dropped"]) > 0 or len(data["entered"]) > 0
        for data in results.values()
    )
    assert any_changes
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_analysis.py -v`
Expected: FAIL — `signal_analysis` module not found.

- [ ] **Step 3: Implement Phase A and Phase B**

```python
# signal_analysis.py
"""
Analysis engine for the signal wargaming experiment.

Runs four phases: individual signal profiling (A), ablation (B),
degraded scenarios (C), and recommendation synthesis (D).
"""

import logging
from signal_scoring import (
    ALL_SIGNALS, DEFAULT_WEIGHTS,
    score_candidates_multisignal,
)

log = logging.getLogger("signal_analysis")

TOP_N = 25


def _run_scoring(cache, signals, weights, **kwargs):
    """Convenience wrapper for scoring with given weights."""
    return score_candidates_multisignal(cache, signals, weights, **kwargs)


def _top_names(ranked, n):
    """Extract top N artist names from ranked list."""
    return [name for _, name in ranked[:n]]


def _overlap_pct(list_a, list_b):
    """Percentage of list_a items that appear in list_b."""
    if not list_a:
        return 0.0
    set_b = set(list_b)
    return 100.0 * sum(1 for x in list_a if x in set_b) / len(list_a)


def run_phase_a(cache, signals, top_n=TOP_N, **scoring_kwargs):
    """Phase A: Individual Signal Profiling.

    Runs scoring with each signal solo (weight=1.0, all others 0.0).

    Returns:
        {signal_name: {
            "ranked": [(score, name), ...],
            "unique": [names only in this signal's top N],
            "baseline_overlap": float percentage,
        }}
    """
    # First compute favorites-only baseline
    baseline_weights = {s: 0.0 for s in ALL_SIGNALS}
    baseline_weights["favorites"] = 1.0
    baseline_ranked = _run_scoring(cache, signals, baseline_weights, **scoring_kwargs)
    baseline_names = _top_names(baseline_ranked, top_n)

    # Run each signal solo
    solo_results = {}
    for sig in ALL_SIGNALS:
        weights = {s: 0.0 for s in ALL_SIGNALS}
        weights[sig] = 1.0
        ranked = _run_scoring(cache, signals, weights, **scoring_kwargs)
        solo_results[sig] = {
            "ranked": ranked,
            "top_names": _top_names(ranked, top_n),
        }

    # Compute unique artists and baseline overlap
    results = {}
    for sig in ALL_SIGNALS:
        other_names = set()
        for other_sig in ALL_SIGNALS:
            if other_sig != sig:
                other_names.update(solo_results[other_sig]["top_names"])
        unique = [n for n in solo_results[sig]["top_names"] if n not in other_names]
        overlap = _overlap_pct(solo_results[sig]["top_names"], baseline_names)
        results[sig] = {
            "ranked": solo_results[sig]["ranked"],
            "unique": unique,
            "baseline_overlap": overlap,
        }

    return results


def run_phase_b(cache, signals, top_n=TOP_N, **scoring_kwargs):
    """Phase B: Ablation — drop one signal at a time from all-on.

    Starts with all signals at weight=1.0, then zeroes one per run.

    Returns:
        {signal_name: {
            "ranked": [(score, name), ...],
            "dropped": [names that left top N],
            "entered": [names that entered top N],
        }}
    """
    # All-on baseline
    all_on = {s: 1.0 for s in ALL_SIGNALS}
    all_ranked = _run_scoring(cache, signals, all_on, **scoring_kwargs)
    all_names = _top_names(all_ranked, top_n)

    results = {}
    for sig in ALL_SIGNALS:
        weights = {s: 1.0 for s in ALL_SIGNALS}
        weights[sig] = 0.0
        ranked = _run_scoring(cache, signals, weights, **scoring_kwargs)
        ablated_names = _top_names(ranked, top_n)
        dropped = [n for n in all_names if n not in ablated_names]
        entered = [n for n in ablated_names if n not in all_names]
        results[sig] = {
            "ranked": ranked,
            "dropped": dropped,
            "entered": entered,
        }

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_analysis.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add signal_analysis.py tests/test_signal_analysis.py
git commit -m "feat: add Phase A (signal profiling) and Phase B (ablation) analysis"
```

---

### Task 6: Analysis Phases C & D — Degraded Scenarios and Recommendations

**Files:**
- Modify: `signal_analysis.py`
- Modify: `tests/test_signal_analysis.py`

- [ ] **Step 1: Write failing tests for Phase C**

Add to `tests/test_signal_analysis.py`:

```python
def test_phase_c_produces_all_scenarios():
    """Phase C should produce results for all defined scenarios."""
    from signal_analysis import run_phase_c, SCENARIOS
    cache, signals = _make_test_data()
    results = run_phase_c(cache, signals, top_n=10)
    assert set(results.keys()) == set(SCENARIOS.keys())
    for scenario_name, data in results.items():
        assert "ranked" in data
        assert "full_overlap" in data
        assert "weights" in data


def test_phase_c_baseline_uses_only_favorites():
    """Baseline scenario should only use favorites signal."""
    from signal_analysis import run_phase_c
    cache, signals = _make_test_data()
    results = run_phase_c(cache, signals, top_n=10)
    w = results["baseline"]["weights"]
    assert w["favorites"] > 0
    assert w["playcount"] == 0
    assert w["heavy_rotation"] == 0


def test_phase_c_no_favorites_zeroes_favorites():
    """No-favorites scenario must have favorites weight = 0."""
    from signal_analysis import run_phase_c
    cache, signals = _make_test_data()
    results = run_phase_c(cache, signals, top_n=10)
    assert results["no_favorites"]["weights"]["favorites"] == 0.0


def test_phase_c_light_listener_caps_playcount():
    """Light listener scenario should cap play counts."""
    from signal_analysis import run_phase_c
    cache, signals = _make_test_data()
    results = run_phase_c(cache, signals, top_n=10)
    assert "caps" in results["light_listener"]
    assert results["light_listener"]["caps"].get("playcount") == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_analysis.py -k "phase_c" -v`
Expected: FAIL — `run_phase_c` not found.

- [ ] **Step 3: Implement Phase C**

Add to `signal_analysis.py`:

```python
SCENARIOS = {
    "baseline": {
        "desc": "Current behavior — favorites only",
        "weights": {"favorites": 1.0, "playcount": 0.0, "playlists": 0.0,
                    "heavy_rotation": 0.0, "recommendations": 0.0},
    },
    "full_signals": {
        "desc": "All signals active at equal weight",
        "weights": {"favorites": 1.0, "playcount": 1.0, "playlists": 1.0,
                    "heavy_rotation": 1.0, "recommendations": 1.0},
    },
    "no_favorites": {
        "desc": "User doesn't favorite — all other signals",
        "weights": {"favorites": 0.0, "playcount": 1.0, "playlists": 1.0,
                    "heavy_rotation": 1.0, "recommendations": 1.0},
    },
    "light_listener": {
        "desc": "Favorites but low engagement — capped play count, no playlists/rotation",
        "weights": {"favorites": 1.0, "playcount": 1.0, "playlists": 0.0,
                    "heavy_rotation": 0.0, "recommendations": 1.0},
        "caps": {"playcount": 5},
    },
    "api_only": {
        "desc": "No local data — only API signals",
        "weights": {"favorites": 0.0, "playcount": 0.0, "playlists": 0.0,
                    "heavy_rotation": 1.0, "recommendations": 1.0},
    },
    "jxa_only": {
        "desc": "No API user token — only local JXA signals",
        "weights": {"favorites": 1.0, "playcount": 1.0, "playlists": 1.0,
                    "heavy_rotation": 0.0, "recommendations": 0.0},
    },
}


def run_phase_c(cache, signals, top_n=TOP_N, **scoring_kwargs):
    """Phase C: Degraded Scenarios.

    Runs predefined scenarios simulating different user situations.

    Returns:
        {scenario_name: {
            "desc": str,
            "ranked": [(score, name), ...],
            "weights": {signal: weight},
            "caps": {signal: cap} or {},
            "full_overlap": float percentage overlap with full_signals,
        }}
    """
    # Run full-signals first for comparison baseline
    full_weights = SCENARIOS["full_signals"]["weights"]
    full_ranked = _run_scoring(cache, signals, full_weights, **scoring_kwargs)
    full_names = _top_names(full_ranked, top_n)

    results = {}
    for name, scenario in SCENARIOS.items():
        caps = scenario.get("caps", {})
        ranked = _run_scoring(cache, signals, scenario["weights"],
                              caps=caps, **scoring_kwargs)
        scenario_names = _top_names(ranked, top_n)
        results[name] = {
            "desc": scenario["desc"],
            "ranked": ranked,
            "weights": scenario["weights"],
            "caps": caps,
            "full_overlap": _overlap_pct(scenario_names, full_names),
        }

    return results
```

- [ ] **Step 4: Run Phase C tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_analysis.py -k "phase_c" -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Write failing tests for Phase D**

Add to `tests/test_signal_analysis.py`:

```python
def test_phase_d_produces_recommendations():
    """Phase D should produce 3-5 recommended configurations."""
    from signal_analysis import run_phase_d
    cache, signals = _make_test_data()
    recs = run_phase_d(cache, signals, top_n=10)
    assert 3 <= len(recs) <= 5
    for rec in recs:
        assert "name" in rec
        assert "rationale" in rec
        assert "weights" in rec
        assert "ranked" in rec
        assert "baseline_diff" in rec


def test_phase_d_recommendations_have_different_weights():
    """Each recommendation should have a distinct weight configuration."""
    from signal_analysis import run_phase_d
    cache, signals = _make_test_data()
    recs = run_phase_d(cache, signals, top_n=10)
    weight_tuples = [tuple(sorted(r["weights"].items())) for r in recs]
    assert len(set(weight_tuples)) == len(weight_tuples)


def test_phase_d_baseline_diff_contains_entered_and_dropped():
    """Each recommendation's baseline diff should list entered and dropped artists."""
    from signal_analysis import run_phase_d
    cache, signals = _make_test_data()
    recs = run_phase_d(cache, signals, top_n=10)
    for rec in recs:
        assert "entered" in rec["baseline_diff"]
        assert "dropped" in rec["baseline_diff"]
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_analysis.py -k "phase_d" -v`
Expected: FAIL — `run_phase_d` not found.

- [ ] **Step 7: Implement Phase D**

Add to `signal_analysis.py`:

```python
def run_phase_d(cache, signals, top_n=TOP_N, **scoring_kwargs):
    """Phase D: Synthesize 3-5 recommended weight configurations.

    Analyzes phase A-C data to propose configurations optimized for
    different goals. Each recommendation includes weights, rationale,
    ranking, and diff vs baseline.

    Returns:
        List of recommendation dicts, each containing:
            name, rationale, weights, ranked, baseline_diff
    """
    # Compute baseline for diff comparisons
    baseline_weights = {"favorites": 1.0, "playcount": 0.0, "playlists": 0.0,
                        "heavy_rotation": 0.0, "recommendations": 0.0}
    baseline_ranked = _run_scoring(cache, signals, baseline_weights, **scoring_kwargs)
    baseline_names = _top_names(baseline_ranked, top_n)

    # Run Phase A to understand signal contributions
    phase_a = run_phase_a(cache, signals, top_n=top_n, **scoring_kwargs)

    # Determine which signals have unique contributions
    active_signals = set()
    for sig in ALL_SIGNALS:
        data = phase_a[sig]
        if len(data["ranked"]) > 0:
            active_signals.add(sig)

    # Build recommendations — start from templates, then zero out
    # any signal that has no data (active_signals check)
    recommendations = [
        {
            "name": "Favorites-Heavy",
            "rationale": "Favorites dominate, with play count as secondary confirmation. "
                         "Best for users who actively favorite songs.",
            "weights": {"favorites": 1.0, "playcount": 0.3, "playlists": 0.1,
                        "heavy_rotation": 0.1, "recommendations": 0.1},
        },
        {
            "name": "Engagement-Balanced",
            "rationale": "Balances explicit preference (favorites) with engagement depth "
                         "(play count, playlists). Good all-around default.",
            "weights": {"favorites": 1.0, "playcount": 0.5, "playlists": 0.3,
                        "heavy_rotation": 0.2, "recommendations": 0.2},
        },
        {
            "name": "Engagement-Heavy",
            "rationale": "Play count and playlists weighted nearly as high as favorites. "
                         "Surfaces artists the user listens to heavily even without favoriting.",
            "weights": {"favorites": 0.8, "playcount": 0.8, "playlists": 0.5,
                        "heavy_rotation": 0.3, "recommendations": 0.2},
        },
        {
            "name": "No-Favorites Fallback",
            "rationale": "Designed for users who never favorite. Play count is primary, "
                         "supplemented by playlists and Apple signals.",
            "weights": {"favorites": 0.0, "playcount": 1.0, "playlists": 0.5,
                        "heavy_rotation": 0.3, "recommendations": 0.3},
        },
        {
            "name": "Discovery-Maximizer",
            "rationale": "Weights all signals equally to maximize breadth. "
                         "Surfaces the widest variety of candidates across all signals.",
            "weights": {"favorites": 1.0, "playcount": 1.0, "playlists": 1.0,
                        "heavy_rotation": 1.0, "recommendations": 1.0},
        },
    ]

    # Zero out weights for signals with no data
    for rec in recommendations:
        for sig in ALL_SIGNALS:
            if sig not in active_signals:
                rec["weights"][sig] = 0.0

    # Drop any configs that become identical after zeroing inactive signals
    seen = set()
    unique_recs = []
    for rec in recommendations:
        key = tuple(sorted(rec["weights"].items()))
        if key not in seen:
            seen.add(key)
            unique_recs.append(rec)
    recommendations = unique_recs

    # Score each recommendation and compute baseline diff
    for rec in recommendations:
        ranked = _run_scoring(cache, signals, rec["weights"], **scoring_kwargs)
        rec["ranked"] = ranked
        rec_names = _top_names(ranked, top_n)
        rec["baseline_diff"] = {
            "entered": [n for n in rec_names if n not in baseline_names],
            "dropped": [n for n in baseline_names if n not in rec_names],
        }

    return recommendations
```

- [ ] **Step 8: Run all analysis tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_analysis.py -v`
Expected: All 13 tests PASS.

- [ ] **Step 9: Commit**

```bash
git add signal_analysis.py tests/test_signal_analysis.py
git commit -m "feat: add Phase C (degraded scenarios) and Phase D (recommendations) analysis"
```

---

### Task 7: Report Generation

**Files:**
- Create: `signal_report.py`
- Create: `tests/test_signal_report.py`

Generates the narrative wargaming report from analysis results.

- [ ] **Step 1: Write failing tests for report generation**

```python
# tests/test_signal_report.py
import pytest


def _make_fake_analysis():
    """Build minimal fake analysis results for report testing."""
    from signal_scoring import ALL_SIGNALS

    phase_a = {}
    for sig in ALL_SIGNALS:
        phase_a[sig] = {
            "ranked": [(1.0, "artist_a"), (0.5, "artist_b")],
            "unique": ["artist_a"] if sig == "playcount" else [],
            "baseline_overlap": 80.0 if sig != "favorites" else 100.0,
        }

    phase_b = {}
    for sig in ALL_SIGNALS:
        phase_b[sig] = {
            "ranked": [(1.0, "artist_a"), (0.5, "artist_b")],
            "dropped": ["artist_c"] if sig == "favorites" else [],
            "entered": ["artist_d"] if sig == "favorites" else [],
        }

    phase_c = {
        "baseline": {
            "desc": "Favorites only", "ranked": [(1.0, "a")],
            "weights": {"favorites": 1.0}, "caps": {}, "full_overlap": 70.0,
        },
        "full_signals": {
            "desc": "All on", "ranked": [(1.0, "a"), (0.5, "b")],
            "weights": {s: 1.0 for s in ALL_SIGNALS}, "caps": {}, "full_overlap": 100.0,
        },
    }

    phase_d = [
        {
            "name": "Balanced",
            "rationale": "Good default",
            "weights": {"favorites": 1.0, "playcount": 0.5, "playlists": 0.3,
                        "heavy_rotation": 0.2, "recommendations": 0.2},
            "ranked": [(1.0, "artist_a"), (0.8, "artist_b")],
            "baseline_diff": {"entered": ["artist_b"], "dropped": []},
        },
    ]

    return phase_a, phase_b, phase_c, phase_d


def test_generate_report_contains_all_phases():
    """Report should contain sections for all four phases."""
    from signal_report import generate_wargaming_report
    a, b, c, d = _make_fake_analysis()
    report = generate_wargaming_report(a, b, c, d, library_count=1000)
    assert "Phase A" in report
    assert "Phase B" in report
    assert "Phase C" in report
    assert "Phase D" in report


def test_generate_report_contains_signal_names():
    """Report should mention each signal by name."""
    from signal_report import generate_wargaming_report
    a, b, c, d = _make_fake_analysis()
    report = generate_wargaming_report(a, b, c, d, library_count=1000)
    for sig in ["favorites", "playcount", "playlists", "heavy_rotation", "recommendations"]:
        assert sig in report.lower() or sig.replace("_", " ") in report.lower()


def test_generate_report_contains_recommendation_names():
    """Report should include each recommendation's name and rationale."""
    from signal_report import generate_wargaming_report
    a, b, c, d = _make_fake_analysis()
    report = generate_wargaming_report(a, b, c, d, library_count=1000)
    assert "Balanced" in report
    assert "Good default" in report


def test_generate_report_is_string():
    """Report should be a plain string."""
    from signal_report import generate_wargaming_report
    a, b, c, d = _make_fake_analysis()
    report = generate_wargaming_report(a, b, c, d, library_count=1000)
    assert isinstance(report, str)
    assert len(report) > 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_report.py -v`
Expected: FAIL — `signal_report` module not found.

- [ ] **Step 3: Implement report generation**

```python
# signal_report.py
"""
Report generation for the signal wargaming experiment.

Produces a formatted markdown report from analysis phase results.
"""

import datetime
from signal_scoring import ALL_SIGNALS

SIGNAL_DISPLAY = {
    "favorites": "Favorites",
    "playcount": "Play Count",
    "playlists": "Playlist Membership",
    "heavy_rotation": "Heavy Rotation",
    "recommendations": "Personal Recs",
}

TOP_N = 25


def _format_ranked(ranked, n=TOP_N):
    """Format a ranked list as numbered lines."""
    lines = []
    for i, (score, name) in enumerate(ranked[:n], 1):
        lines.append(f"  {i:>2}. {name:<35s} ({score:.3f})")
    return "\n".join(lines) if lines else "  (no candidates)"


def _format_weights(weights):
    """Format weights dict as a compact string."""
    parts = []
    for sig in ALL_SIGNALS:
        w = weights.get(sig, 0.0)
        if w > 0:
            parts.append(f"{SIGNAL_DISPLAY[sig]}={w}")
    return ", ".join(parts) if parts else "(all zero)"


def generate_wargaming_report(phase_a, phase_b, phase_c, phase_d,
                               library_count=0, top_n=TOP_N):
    """Generate the full wargaming report.

    Args:
        phase_a: output of run_phase_a()
        phase_b: output of run_phase_b()
        phase_c: output of run_phase_c()
        phase_d: output of run_phase_d()
        library_count: number of library artists
        top_n: number of artists to show per section

    Returns:
        Formatted report string (markdown).
    """
    lines = []
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    sep = "=" * 70

    # Header
    lines.append(f"# Signal Wargaming Results — {date_str}")
    lines.append(f"Library artists: {library_count}")
    lines.append(f"Top N: {top_n}")
    lines.append("")

    # Phase A
    lines.append(f"## Phase A — Individual Signal Profiling")
    lines.append("")
    lines.append("Each signal run solo (weight=1.0, all others zeroed).")
    lines.append("")
    for sig in ALL_SIGNALS:
        data = phase_a.get(sig, {})
        display = SIGNAL_DISPLAY.get(sig, sig)
        lines.append(f"### {display}")
        lines.append(f"Baseline overlap: {data.get('baseline_overlap', 0):.0f}%")
        unique = data.get("unique", [])
        if unique:
            lines.append(f"Unique to this signal: {', '.join(unique)}")
        else:
            lines.append("No unique artists (all appear in other signals' top lists)")
        lines.append(f"\nTop {top_n}:")
        lines.append(_format_ranked(data.get("ranked", []), top_n))
        lines.append("")

    # Phase B
    lines.append(f"## Phase B — Ablation (drop one signal at a time)")
    lines.append("")
    lines.append("Starting from all signals at weight=1.0, zero one signal per run.")
    lines.append("")
    for sig in ALL_SIGNALS:
        data = phase_b.get(sig, {})
        display = SIGNAL_DISPLAY.get(sig, sig)
        dropped = data.get("dropped", [])
        entered = data.get("entered", [])
        lines.append(f"### Without {display}")
        if not dropped and not entered:
            lines.append("No change to top list — this signal has no marginal impact.")
        else:
            if dropped:
                lines.append(f"Dropped: {', '.join(dropped)}")
            if entered:
                lines.append(f"Entered: {', '.join(entered)}")
        lines.append("")

    # Phase C
    lines.append(f"## Phase C — Degraded Scenarios")
    lines.append("")
    for scenario_name, data in phase_c.items():
        lines.append(f"### {scenario_name.replace('_', ' ').title()}")
        lines.append(f"*{data.get('desc', '')}*")
        lines.append(f"Weights: {_format_weights(data.get('weights', {}))}")
        caps = data.get("caps", {})
        if caps:
            cap_str = ", ".join(f"{SIGNAL_DISPLAY.get(k,k)} capped at {v}" for k, v in caps.items())
            lines.append(f"Caps: {cap_str}")
        lines.append(f"Overlap with full signals: {data.get('full_overlap', 0):.0f}%")
        lines.append(f"\nTop {top_n}:")
        lines.append(_format_ranked(data.get("ranked", []), top_n))
        lines.append("")

    # Phase D
    lines.append(f"## Phase D — Recommended Configurations")
    lines.append("")
    for i, rec in enumerate(phase_d, 1):
        lines.append(f"### Option {i}: {rec['name']}")
        lines.append(f"**Rationale:** {rec['rationale']}")
        lines.append(f"**Weights:** {_format_weights(rec['weights'])}")
        diff = rec.get("baseline_diff", {})
        entered = diff.get("entered", [])
        dropped = diff.get("dropped", [])
        if entered:
            lines.append(f"**New vs baseline:** {', '.join(entered)}")
        if dropped:
            lines.append(f"**Dropped vs baseline:** {', '.join(dropped)}")
        lines.append(f"\nTop {top_n}:")
        lines.append(_format_ranked(rec.get("ranked", []), top_n))
        lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_report.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add signal_report.py tests/test_signal_report.py
git commit -m "feat: add wargaming report generator with narrative for all four phases"
```

---

### Task 8: Main Experiment Script — Data Collection and Analysis

**Files:**
- Create: `signal_experiment.py`
- Create: `tests/test_signal_experiment.py`

The entry point that orchestrates data collection, caching, analysis, and report generation.

- [ ] **Step 1: Write failing tests for data collection orchestration**

```python
# tests/test_signal_experiment.py
import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


def test_collect_all_signals_caches_results(tmp_path):
    """Should cache all signal data to JSON files."""
    from signal_experiment import collect_all_signals
    mock_favorites = {"haken": 5, "tool": 2}
    mock_playcounts = {"haken": 100, "tool": 50}
    mock_playlists = {"haken": 3}
    mock_hr = {"haken", "tool"}
    mock_recs = {"meshuggah"}

    with patch("signal_experiment.parse_library_jxa", return_value=mock_favorites), \
         patch("signal_experiment.collect_playcounts_jxa", return_value=mock_playcounts), \
         patch("signal_experiment.collect_user_playlists_jxa", return_value=mock_playlists), \
         patch("signal_experiment.collect_heavy_rotation", return_value=mock_hr), \
         patch("signal_experiment.collect_recommendations", return_value=mock_recs):
        signals = collect_all_signals(
            cache_dir=tmp_path,
            api_session=MagicMock(),
        )

    assert signals["favorites"] == mock_favorites
    assert signals["playcount"] == mock_playcounts
    assert signals["playlists"] == mock_playlists
    assert signals["heavy_rotation"] == mock_hr
    assert signals["recommendations"] == mock_recs

    # Verify caching
    assert (tmp_path / "playcount_cache.json").exists()
    assert (tmp_path / "playlist_membership_cache.json").exists()
    assert (tmp_path / "heavy_rotation_cache.json").exists()
    assert (tmp_path / "recommendations_cache.json").exists()


def test_collect_all_signals_loads_from_cache(tmp_path):
    """Should load from cache when files exist instead of re-collecting."""
    from signal_experiment import collect_all_signals
    # Pre-populate caches
    (tmp_path / "playcount_cache.json").write_text(json.dumps({"haken": 100}))
    (tmp_path / "playlist_membership_cache.json").write_text(json.dumps({"haken": 3}))
    (tmp_path / "heavy_rotation_cache.json").write_text(json.dumps(["haken"]))
    (tmp_path / "recommendations_cache.json").write_text(json.dumps(["meshuggah"]))

    mock_favorites = {"haken": 5}

    with patch("signal_experiment.parse_library_jxa", return_value=mock_favorites), \
         patch("signal_experiment.collect_playcounts_jxa") as mock_pc, \
         patch("signal_experiment.collect_user_playlists_jxa") as mock_pl, \
         patch("signal_experiment.collect_heavy_rotation") as mock_hr, \
         patch("signal_experiment.collect_recommendations") as mock_rec:
        signals = collect_all_signals(
            cache_dir=tmp_path,
            api_session=MagicMock(),
        )

    # JXA collectors should not have been called
    mock_pc.assert_not_called()
    mock_pl.assert_not_called()
    # API collectors should not have been called
    mock_hr.assert_not_called()
    mock_rec.assert_not_called()

    assert signals["playcount"] == {"haken": 100}
    assert signals["heavy_rotation"] == {"haken"}


def test_collect_all_signals_skips_api_without_session(tmp_path):
    """Without an API session, API signals should be empty sets."""
    from signal_experiment import collect_all_signals
    mock_favorites = {"haken": 5}
    mock_playcounts = {"haken": 100}
    mock_playlists = {"haken": 3}

    with patch("signal_experiment.parse_library_jxa", return_value=mock_favorites), \
         patch("signal_experiment.collect_playcounts_jxa", return_value=mock_playcounts), \
         patch("signal_experiment.collect_user_playlists_jxa", return_value=mock_playlists):
        signals = collect_all_signals(
            cache_dir=tmp_path,
            api_session=None,
        )

    assert signals["heavy_rotation"] == set()
    assert signals["recommendations"] == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_experiment.py -v`
Expected: FAIL — `signal_experiment` module not found.

- [ ] **Step 3: Implement signal_experiment.py**

```python
#!/usr/bin/env python3
"""
Signal Wargaming Experiment

Collects all available preference signals, analyzes their individual
and combined effects on discovery rankings, and recommends weight
configurations for evaluation by listening.

Usage:
    python signal_experiment.py                  # full run
    python signal_experiment.py --skip-api       # skip API signals (no user token)
    python signal_experiment.py --refresh        # re-collect all data (ignore caches)
    python signal_experiment.py --post-listen    # score configs against new favorites
"""

import argparse
import json
import logging
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from music_discovery import (
    _build_paths, load_dotenv, load_cache, load_user_blocklist, parse_library_jxa,
)
from compare_similarity import generate_apple_music_token, AppleMusicClient
from signal_collectors import (
    collect_playcounts_jxa, collect_user_playlists_jxa,
    collect_heavy_rotation, collect_recommendations, _make_user_session,
)
from signal_scoring import score_candidates_multisignal
from signal_analysis import run_phase_a, run_phase_b, run_phase_c, run_phase_d
from signal_report import generate_wargaming_report

log = logging.getLogger("signal_experiment")

TOP_N = 25
REPORT_FILENAME = "signal_wargaming_results.md"


def collect_all_signals(cache_dir, api_session=None, refresh=False):
    """Collect all signals, using caches where available.

    Args:
        cache_dir: Path to cache directory.
        api_session: requests.Session with user token headers, or None to skip API signals.
        refresh: if True, ignore caches and re-collect everything.

    Returns:
        dict with keys: favorites, playcount, playlists, heavy_rotation, recommendations.
    """
    cache_dir = pathlib.Path(cache_dir)

    # Favorites — always fresh from JXA (fast, no cache needed)
    log.info("Reading favorited tracks from Music.app...")
    favorites = parse_library_jxa()
    log.info(f"  {len(favorites)} artists with favorited tracks.")

    # Play counts
    pc_cache = cache_dir / "playcount_cache.json"
    if pc_cache.exists() and not refresh:
        log.info("Loading play counts from cache...")
        playcount = json.loads(pc_cache.read_text())
    else:
        log.info("Reading play counts from Music.app...")
        playcount = collect_playcounts_jxa()
        pc_cache.write_text(json.dumps(playcount, indent=2))
        log.info(f"  {len(playcount)} artists with plays.")

    # Playlist membership
    pl_cache = cache_dir / "playlist_membership_cache.json"
    if pl_cache.exists() and not refresh:
        log.info("Loading playlist membership from cache...")
        playlists = json.loads(pl_cache.read_text())
    else:
        log.info("Reading user playlists from Music.app...")
        playlists = collect_user_playlists_jxa()
        pl_cache.write_text(json.dumps(playlists, indent=2))
        log.info(f"  {len(playlists)} artists across user playlists.")

    # Heavy rotation (API)
    hr_cache = cache_dir / "heavy_rotation_cache.json"
    if hr_cache.exists() and not refresh:
        log.info("Loading heavy rotation from cache...")
        heavy_rotation = set(json.loads(hr_cache.read_text()))
    elif api_session is not None:
        log.info("Fetching heavy rotation from Apple Music API...")
        heavy_rotation = collect_heavy_rotation(api_session)
        hr_cache.write_text(json.dumps(sorted(heavy_rotation), indent=2))
        log.info(f"  {len(heavy_rotation)} heavy rotation artists.")
    else:
        log.info("No API session — skipping heavy rotation.")
        heavy_rotation = set()

    # Recommendations (API)
    rec_cache = cache_dir / "recommendations_cache.json"
    if rec_cache.exists() and not refresh:
        log.info("Loading recommendations from cache...")
        recommendations = set(json.loads(rec_cache.read_text()))
    elif api_session is not None:
        log.info("Fetching personal recommendations from Apple Music API...")
        recommendations = collect_recommendations(api_session)
        rec_cache.write_text(json.dumps(sorted(recommendations), indent=2))
        log.info(f"  {len(recommendations)} recommended artists.")
    else:
        log.info("No API session — skipping recommendations.")
        recommendations = set()

    return {
        "favorites": favorites,
        "playcount": playcount,
        "playlists": playlists,
        "heavy_rotation": heavy_rotation,
        "recommendations": recommendations,
    }


def score_post_listen(saved_recs, new_fav_artists, top_n=10):
    """Score each recommended config against the user's new favorites.

    Args:
        saved_recs: list of recommendation dicts (from Phase D).
        new_fav_artists: set of lowercase artist names newly favorited.
        top_n: how many of each config's top artists to evaluate.

    Returns:
        list of {name, hits, precision, matched} dicts.
    """
    results = []
    for rec in saved_recs:
        top_names = [name for _, name in rec["ranked"][:top_n]]
        hits = [n for n in top_names if n in new_fav_artists]
        precision = len(hits) / len(top_names) * 100 if top_names else 0
        results.append({
            "name": rec["name"],
            "hits": len(hits),
            "precision": precision,
            "matched": hits,
        })
    return results


def run_experiment(signals, scrape_cache, apple_cache, rejected_cache,
                   user_blocklist, top_n=TOP_N):
    """Run all four analysis phases and generate the report.

    Returns:
        (report_string, phase_d_recommendations)
    """
    scoring_kwargs = {
        "apple_cache": apple_cache,
        "apple_weight": 0.2,
        "blocklist_cache": rejected_cache,
        "user_blocklist": user_blocklist,
    }

    log.info("\n--- Phase A: Individual Signal Profiling ---")
    phase_a = run_phase_a(scrape_cache, signals, top_n=top_n, **scoring_kwargs)

    log.info("--- Phase B: Ablation ---")
    phase_b = run_phase_b(scrape_cache, signals, top_n=top_n, **scoring_kwargs)

    log.info("--- Phase C: Degraded Scenarios ---")
    phase_c = run_phase_c(scrape_cache, signals, top_n=top_n, **scoring_kwargs)

    log.info("--- Phase D: Recommendations ---")
    phase_d = run_phase_d(scrape_cache, signals, top_n=top_n, **scoring_kwargs)

    library_count = len(set().union(
        signals["favorites"].keys(),
        signals["playcount"].keys(),
        signals["playlists"].keys(),
    ))
    report = generate_wargaming_report(phase_a, phase_b, phase_c, phase_d,
                                        library_count=library_count, top_n=top_n)

    return report, phase_d


def get_evaluation_artists(phase_d, top_n=10):
    """Get the union of top-N artists from all recommended configs.

    Returns:
        sorted list of unique artist names.
    """
    artists = set()
    for rec in phase_d:
        for _, name in rec["ranked"][:top_n]:
            artists.add(name)
    return sorted(artists)


def main():
    parser = argparse.ArgumentParser(description="Signal Wargaming Experiment")
    parser.add_argument("--skip-api", action="store_true",
                        help="Skip API signals (no user token required)")
    parser.add_argument("--refresh", action="store_true",
                        help="Re-collect all data, ignoring caches")
    parser.add_argument("--post-listen", action="store_true",
                        help="Score configs against new favorites after listening")
    parser.add_argument("--build-playlist", action="store_true",
                        help="Build evaluation playlist from recommended configs' top artists")
    parser.add_argument("--top-n", type=int, default=TOP_N,
                        help=f"Number of top artists per analysis (default: {TOP_N})")
    args = parser.parse_args()

    if args.post_listen and args.build_playlist:
        parser.error("Cannot use --post-listen and --build-playlist together")

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    load_dotenv()
    paths = _build_paths()

    # Set up API session if we have a user token
    api_session = None
    if not args.skip_api:
        user_token = os.environ.get("APPLE_MUSIC_USER_TOKEN")
        if user_token:
            dev_token = generate_apple_music_token(
                os.environ.get("APPLE_MUSIC_KEY_ID"),
                os.environ.get("APPLE_MUSIC_TEAM_ID"),
                os.environ.get("APPLE_MUSIC_KEY_PATH"),
            )
            api_session = _make_user_session(dev_token, user_token)
        else:
            log.info("No APPLE_MUSIC_USER_TOKEN found. Run auth_musickit.py first, "
                     "or use --skip-api.")

    cache_dir = paths["cache"].parent

    # Collect signals
    signals = collect_all_signals(cache_dir, api_session, refresh=args.refresh)

    # Load existing caches
    scrape_cache = load_cache(paths["cache"])
    apple_cache_path = cache_dir / "apple_similar_cache.json"
    apple_cache = load_cache(apple_cache_path) if apple_cache_path.exists() else {}
    rejected_cache = load_cache(paths["rejected_scrape"])
    user_blocklist = load_user_blocklist(
        pathlib.Path(__file__).parent / "blocklist.txt")

    if args.post_listen:
        # Re-read favorites (user has favorited new songs since listening)
        new_favorites = parse_library_jxa()
        # Load old favorites from the cached favorites snapshot
        fav_snapshot_path = cache_dir / "favorites_snapshot.json"
        if fav_snapshot_path.exists():
            old_favorites = json.loads(fav_snapshot_path.read_text())
        else:
            log.error("No favorites snapshot found. Run the experiment first.")
            sys.exit(1)
        new_fav_artists = set(new_favorites.keys()) - set(old_favorites.keys())
        log.info(f"\nNew favorites since last run: {len(new_fav_artists)} artists")
        if new_fav_artists:
            log.info(f"  {', '.join(sorted(new_fav_artists))}")

        # Load saved recommendations
        recs_path = cache_dir / "signal_wargaming_recs.json"
        if not recs_path.exists():
            log.error("No saved recommendations found. Run the experiment first.")
            sys.exit(1)
        saved_recs = json.loads(recs_path.read_text())

        results = score_post_listen(saved_recs, new_fav_artists)
        log.info("\n=== Post-Listen Scoring ===\n")
        for r in results:
            log.info(f"{r['name']}:")
            log.info(f"  Hits: {r['hits']}/10 ({r['precision']:.0f}% precision)")
            if r["matched"]:
                log.info(f"  Matched: {', '.join(r['matched'])}")
        return

    # Run experiment
    report, phase_d = run_experiment(
        signals, scrape_cache, apple_cache, rejected_cache,
        user_blocklist, top_n=args.top_n)

    # Save report
    report_path = pathlib.Path(__file__).parent / REPORT_FILENAME
    report_path.write_text(report)
    log.info(f"\nReport saved to: {report_path}")

    # Save favorites snapshot for post-listen comparison
    fav_snapshot_path = cache_dir / "favorites_snapshot.json"
    fav_snapshot_path.write_text(json.dumps(signals["favorites"], indent=2))

    # Save recommendations for post-listen scoring
    recs_path = cache_dir / "signal_wargaming_recs.json"
    serializable_recs = []
    for rec in phase_d:
        serializable_recs.append({
            "name": rec["name"],
            "rationale": rec["rationale"],
            "weights": rec["weights"],
            "ranked": rec["ranked"][:25],
            "baseline_diff": rec["baseline_diff"],
        })
    recs_path.write_text(json.dumps(serializable_recs, indent=2))

    # Show evaluation artists
    eval_artists = get_evaluation_artists(phase_d, top_n=10)
    log.info(f"\n=== Evaluation Playlist Artists ({len(eval_artists)}) ===")
    for a in eval_artists:
        log.info(f"  {a}")
    log.info(f"\nTo build the evaluation playlist, run:")
    log.info(f"  python signal_experiment.py --build-playlist")
    log.info(f"\nAfter listening and favoriting, run:")
    log.info(f"  python signal_experiment.py --post-listen")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_experiment.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add signal_experiment.py tests/test_signal_experiment.py
git commit -m "feat: add signal wargaming experiment script with data collection, analysis, and reporting"
```

---

### Task 9: Evaluation Playlist Builder

**Files:**
- Modify: `signal_experiment.py`
- Modify: `tests/test_signal_experiment.py`

Add `--build-playlist` flag that builds a Music Discovery playlist from the union of all recommended configs' top 10 artists (2-3 tracks each).

- [ ] **Step 1: Write failing test for playlist artist selection**

Add to `tests/test_signal_experiment.py`:

```python
def test_get_evaluation_artists_union_of_top_10():
    """Should return union of top-10 artists across all recommendations."""
    from signal_experiment import get_evaluation_artists
    recs = [
        {"name": "A", "ranked": [(1.0, f"artist_{i}") for i in range(25)]},
        {"name": "B", "ranked": [(1.0, f"other_{i}") for i in range(25)]},
    ]
    artists = get_evaluation_artists(recs, top_n=10)
    # 10 from each, union
    assert len(artists) == 20
    assert "artist_0" in artists
    assert "other_0" in artists
    assert "artist_15" not in artists  # beyond top 10


def test_get_evaluation_artists_deduplicates():
    """Artists appearing in multiple configs should only appear once."""
    from signal_experiment import get_evaluation_artists
    recs = [
        {"name": "A", "ranked": [(1.0, "haken"), (0.9, "tool")]},
        {"name": "B", "ranked": [(1.0, "haken"), (0.9, "meshuggah")]},
    ]
    artists = get_evaluation_artists(recs, top_n=10)
    assert artists.count("haken") <= 1  # sorted list, no dupes
    assert set(artists) == {"haken", "tool", "meshuggah"}
```

- [ ] **Step 2: Run tests to verify they pass (these test existing code)**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_experiment.py -k "evaluation_artists" -v`
Expected: PASS — `get_evaluation_artists` was already implemented in Task 8.

- [ ] **Step 3: Add `--build-playlist` handling to main()**

Add to `signal_experiment.py` in the argparse section:

```python
    parser.add_argument("--build-playlist", action="store_true",
                        help="Build evaluation playlist from recommended configs' top artists")
```

Add before the `if args.post_listen:` block in `main()`:

```python
    if args.build_playlist:
        recs_path = cache_dir / "signal_wargaming_recs.json"
        if not recs_path.exists():
            log.error("No saved recommendations found. Run the experiment first.")
            sys.exit(1)
        saved_recs = json.loads(recs_path.read_text())
        eval_artists = get_evaluation_artists(saved_recs, top_n=10)
        log.info(f"\nBuilding evaluation playlist with {len(eval_artists)} artists...")

        # Import playlist infrastructure
        from music_discovery import (
            setup_playlist, search_itunes, add_track_to_playlist,
            fetch_top_tracks, RATE_LIMIT,
        )
        import time

        if not setup_playlist():
            log.error("Could not create playlist — aborting.")
            sys.exit(1)

        api_key = os.environ.get("LASTFM_API_KEY")
        added = 0
        for i, artist in enumerate(eval_artists, 1):
            log.info(f"[{i}/{len(eval_artists)}] {artist}")
            tracks = fetch_top_tracks(artist, api_key) if api_key else []
            artist_added = 0
            for track in tracks[:3]:  # 2-3 tracks per artist
                track_id = search_itunes(artist, track["name"])
                if track_id:
                    if add_track_to_playlist(artist, track["name"]):
                        artist_added += 1
                        added += 1
                if artist_added >= 2:
                    break
            time.sleep(RATE_LIMIT)

        log.info(f"\nEvaluation playlist built: {added} tracks from {len(eval_artists)} artists.")
        log.info("Listen, favorite what you like, then run:")
        log.info("  python signal_experiment.py --post-listen")
        return
```

- [ ] **Step 4: Run all experiment tests to verify nothing broke**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_experiment.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add signal_experiment.py tests/test_signal_experiment.py
git commit -m "feat: add --build-playlist flag for evaluation playlist from recommended configs"
```

---

### Task 10: Update .env.example

**Files:**
- Modify: `.env.example`

Note: New cache paths are managed directly by `signal_experiment.py` using `cache_dir`, not registered in `_build_paths`. This keeps the experiment self-contained.

- [ ] **Step 1: Update .env.example with user token field**

Add to `.env.example` after the Apple Music API credentials section:

```
# Apple Music User Token (for heavy rotation, recommendations)
# Run: python auth_musickit.py   to obtain this automatically
APPLE_MUSIC_USER_TOKEN=
```

- [ ] **Step 2: Run existing tests to verify nothing broke**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest -x -q`
Expected: All existing tests PASS.

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "docs: add APPLE_MUSIC_USER_TOKEN to .env.example"
```

---

### Task 11: Integration Test — Full Experiment with Mocked Data

**Files:**
- Modify: `tests/test_signal_experiment.py`

End-to-end test that runs the full experiment pipeline with mocked signal data and verifies the report is generated correctly.

- [ ] **Step 1: Write integration test**

Add to `tests/test_signal_experiment.py`:

```python
def test_full_experiment_produces_report(tmp_path):
    """Full experiment should produce a report with all phases."""
    from signal_experiment import collect_all_signals, run_experiment, get_evaluation_artists

    # Build realistic mock data
    scrape_cache = {
        "haken": {"umpfel": 0.9, "native construct": 0.8, "caligulas horse": 0.7},
        "tool": {"meshuggah": 0.8, "umpfel": 0.6, "gojira": 0.5},
        "radiohead": {"portishead": 0.7, "massive attack": 0.6, "bjork": 0.5},
    }
    apple_cache = {
        "haken": ["leprous", "between the buried and me"],
        "tool": ["a perfect circle", "deftones"],
    }
    rejected_cache = {
        "reo speedwagon": {"journey": 0.9, "foreigner": 0.8},
    }
    user_blocklist = {"reo speedwagon"}

    mock_favorites = {"haken": 5, "tool": 3, "radiohead": 2}
    mock_playcounts = {"haken": 100, "tool": 50, "radiohead": 30, "adele": 200}
    mock_playlists = {"haken": 3, "radiohead": 2}
    mock_hr = {"tool", "radiohead"}
    mock_recs = {"haken", "bjork"}

    with patch("signal_experiment.parse_library_jxa", return_value=mock_favorites), \
         patch("signal_experiment.collect_playcounts_jxa", return_value=mock_playcounts), \
         patch("signal_experiment.collect_user_playlists_jxa", return_value=mock_playlists), \
         patch("signal_experiment.collect_heavy_rotation", return_value=mock_hr), \
         patch("signal_experiment.collect_recommendations", return_value=mock_recs):
        signals = collect_all_signals(cache_dir=tmp_path, api_session=MagicMock())

    report, phase_d = run_experiment(
        signals, scrape_cache, apple_cache, rejected_cache,
        user_blocklist, top_n=10)

    # Report should contain all phases
    assert "Phase A" in report
    assert "Phase B" in report
    assert "Phase C" in report
    assert "Phase D" in report

    # Should have recommendations
    assert len(phase_d) >= 3
    for rec in phase_d:
        assert len(rec["ranked"]) > 0

    # Evaluation artists should be a non-empty set
    eval_artists = get_evaluation_artists(phase_d, top_n=10)
    assert len(eval_artists) > 0
```

- [ ] **Step 2: Run integration test**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_experiment.py::test_full_experiment_produces_report -v`
Expected: PASS.

- [ ] **Step 3: Run full test suite**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest -v`
Expected: All tests PASS (existing + new).

- [ ] **Step 4: Commit**

```bash
git add tests/test_signal_experiment.py
git commit -m "test: add integration test for full signal wargaming experiment pipeline"
```

---

### Task 12: Post-Listen Scoring Tests

**Files:**
- Modify: `tests/test_signal_experiment.py`

- [ ] **Step 1: Write test for post-listen scoring logic**

Add to `tests/test_signal_experiment.py`:

```python
def test_post_listen_scoring(tmp_path):
    """Post-listen should score each config against new favorites."""
    # Save fake recommendations
    recs = [
        {"name": "Config A", "weights": {}, "rationale": "test",
         "ranked": [(1.0, "haken"), (0.9, "tool"), (0.8, "meshuggah"),
                    (0.7, "gojira"), (0.6, "umpfel"), (0.5, "leprous"),
                    (0.4, "bjork"), (0.3, "portishead"), (0.2, "massive attack"),
                    (0.1, "radiohead")],
         "baseline_diff": {"entered": [], "dropped": []}},
        {"name": "Config B", "weights": {}, "rationale": "test",
         "ranked": [(1.0, "bjork"), (0.9, "portishead"), (0.8, "massive attack"),
                    (0.7, "haken"), (0.6, "tool"), (0.5, "meshuggah"),
                    (0.4, "gojira"), (0.3, "umpfel"), (0.2, "leprous"),
                    (0.1, "radiohead")],
         "baseline_diff": {"entered": [], "dropped": []}},
    ]
    recs_path = tmp_path / "signal_wargaming_recs.json"
    recs_path.write_text(json.dumps(recs))

    from signal_experiment import score_post_listen

    # User favorited haken and bjork after listening
    new_fav_artists = {"haken", "bjork"}
    results = score_post_listen(recs, new_fav_artists, top_n=10)

    assert len(results) == 2
    # Config A: haken at #1, bjork at #7 → 2 hits
    assert results[0]["name"] == "Config A"
    assert results[0]["hits"] == 2
    assert results[0]["precision"] == 20.0
    # Config B: bjork at #1, haken at #4 → 2 hits
    assert results[1]["name"] == "Config B"
    assert results[1]["hits"] == 2
```

- [ ] **Step 2: Run test to verify it passes**

`score_post_listen` was already defined in Task 8's `signal_experiment.py`. This test validates it.

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_experiment.py::test_post_listen_scoring -v`
Expected: PASS.

- [ ] **Step 3: Run full test suite**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest -v`
Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_signal_experiment.py
git commit -m "test: add post-listen scoring test"
```
