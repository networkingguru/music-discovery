# Apple Music API POC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a comparison POC that fetches similar artists from both Apple Music API and music-map.com, comparing data quality and overlap

**Architecture:** Standalone script that authenticates with Apple Music API via JWT, searches for artists by name to get catalog IDs, fetches similar-artists view, and compares results with existing music-map.com scraper. Outputs a formatted report showing overlap and differences.

**Tech Stack:** Apple Music API, PyJWT, cryptography, requests

---

### Task 1: Add dependencies and credential placeholders

**Files:**
- Modify: `requirements.txt` — add pyjwt, cryptography
- Modify: `.env.example` — add Apple Music API credential placeholders

- [ ] **Step 1: Update `requirements.txt`**

Add `pyjwt` and `cryptography` to `requirements.txt`:

```
requests
beautifulsoup4
playwright
python-dotenv
pyjwt[crypto]
cryptography
```

Note: `pyjwt[crypto]` pulls in `cryptography` as a dependency, but we list `cryptography` explicitly for clarity since we import it directly.

- [ ] **Step 2: Update `.env.example`**

Append Apple Music API credential placeholders to `.env.example`:

```
# Last.fm API key (optional, recommended)
# Get yours at: https://www.last.fm/api/account/create
LASTFM_API_KEY=

# Optional: override default cache/output directories
# CACHE_DIR=~/.cache/music_discovery
# OUTPUT_DIR=~/.cache/music_discovery

# Apple Music API credentials (for compare_similarity.py POC)
# Get these from https://developer.apple.com/account/resources/authkeys/list
APPLE_MUSIC_KEY_ID=
APPLE_MUSIC_TEAM_ID=
APPLE_MUSIC_KEY_PATH=
```

- [ ] **Step 3: Install new dependencies**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && pip install "pyjwt[crypto]" cryptography`

---

### Task 2: Create the standalone POC script

**Files:**
- Create: `compare_similarity.py`

- [ ] **Step 1: Create `compare_similarity.py` with full implementation**

Create the file with the following complete contents:

```python
#!/usr/bin/env python3
"""
Apple Music API vs music-map.com — Similar Artists Comparison POC

Fetches similar artists from both Apple Music API and music-map.com for a
random sample of artists from the user's library, then prints a formatted
comparison report showing overlap and differences.

Usage:
    python compare_similarity.py
    python compare_similarity.py --count 5          # fewer artists
    python compare_similarity.py --artists "Radiohead,Bjork,Portishead"

Requires:
    - Apple Music API credentials in .env (see .env.example)
    - A .p8 private key file from Apple Developer portal
"""

import argparse
import json
import os
import pathlib
import random
import sys
import time

import jwt        # PyJWT
import requests

# ── Project imports ───────────────────────────────────────
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from music_discovery import (
    load_dotenv,
    _resolve_library_path,
    parse_library,
    scrape_musicmap_requests,
)


# ── Constants ─────────────────────────────────────────────
APPLE_MUSIC_BASE = "https://api.music.apple.com/v1/catalog"
STOREFRONT = "us"
TOKEN_TTL = 3600          # 1 hour — max allowed by Apple
API_RATE_LIMIT = 0.5      # seconds between Apple Music API calls
SAMPLE_SIZE = 12           # default number of random artists to compare


# ── JWT Token Generation ─────────────────────────────────
def generate_apple_music_token(key_id, team_id, key_path):
    """Generate a JWT developer token for Apple Music API.

    Args:
        key_id:   The 10-character Key ID from Apple Developer portal.
        team_id:  The 10-character Team ID from Apple Developer portal.
        key_path: Path to the .p8 private key file.

    Returns:
        A signed JWT string valid for TOKEN_TTL seconds.

    Raises:
        FileNotFoundError: If the .p8 key file doesn't exist.
        ValueError: If credentials are empty or key file can't be read.
    """
    if not key_id or not team_id:
        raise ValueError("APPLE_MUSIC_KEY_ID and APPLE_MUSIC_TEAM_ID must be set in .env")

    key_file = pathlib.Path(key_path).expanduser().resolve()
    if not key_file.exists():
        raise FileNotFoundError(f"Apple Music private key not found: {key_file}")

    with open(key_file, "r") as f:
        private_key = f.read()

    now = int(time.time())
    payload = {
        "iss": team_id,
        "iat": now,
        "exp": now + TOKEN_TTL,
    }
    headers = {
        "alg": "ES256",
        "kid": key_id,
    }

    token = jwt.encode(
        payload,
        private_key,
        algorithm="ES256",
        headers=headers,
    )
    return token


# ── Apple Music API Client ───────────────────────────────
class AppleMusicClient:
    """Minimal client for Apple Music catalog API."""

    def __init__(self, token):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
        self.base_url = f"{APPLE_MUSIC_BASE}/{STOREFRONT}"

    def search_artist(self, name):
        """Search for an artist by name. Returns (artist_id, matched_name) or (None, None).

        Uses the catalog search endpoint and picks the best match.
        """
        url = f"{self.base_url}/search"
        params = {
            "term": name,
            "types": "artists",
            "limit": 5,
        }
        try:
            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  [API ERROR] Search failed for '{name}': {e}")
            return None, None

        data = resp.json()
        artists_result = data.get("results", {}).get("artists", {})
        items = artists_result.get("data", [])

        if not items:
            return None, None

        # Try exact match first (case-insensitive)
        name_lower = name.strip().lower()
        for item in items:
            api_name = item.get("attributes", {}).get("name", "")
            if api_name.strip().lower() == name_lower:
                return item["id"], api_name

        # Fall back to first result
        first = items[0]
        return first["id"], first.get("attributes", {}).get("name", name)

    def get_similar_artists(self, artist_id):
        """Fetch similar artists for a given Apple Music artist ID.

        Returns a list of dicts: [{"name": str, "id": str}, ...]
        """
        url = f"{self.base_url}/artists/{artist_id}"
        params = {
            "views": "similar-artists",
        }
        try:
            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  [API ERROR] Similar artists failed for ID {artist_id}: {e}")
            return []

        data = resp.json()

        # The similar-artists view is nested under views
        views = data.get("data", [{}])[0].get("views", {})
        similar_view = views.get("similar-artists", {})
        similar_data = similar_view.get("data", [])

        results = []
        for item in similar_data:
            attrs = item.get("attributes", {})
            results.append({
                "name": attrs.get("name", "Unknown"),
                "id": item.get("id", ""),
            })
        return results


# ── Comparison Logic ─────────────────────────────────────
def compare_for_artist(artist_name, apple_client):
    """Fetch similar artists from both sources and return comparison data.

    Returns a dict:
        {
            "artist": str,
            "apple_id": str or None,
            "apple_matched_name": str or None,
            "apple_similar": [{"name": str, "id": str}, ...],
            "musicmap_similar": {name: proximity_score, ...},
            "overlap": [str, ...],
            "apple_only": [str, ...],
            "musicmap_only": [str, ...],
        }
    """
    result = {
        "artist": artist_name,
        "apple_id": None,
        "apple_matched_name": None,
        "apple_similar": [],
        "musicmap_similar": {},
        "overlap": [],
        "apple_only": [],
        "musicmap_only": [],
    }

    # Fetch from music-map.com
    print(f"  Fetching music-map.com data...")
    musicmap_data = scrape_musicmap_requests(artist_name)
    result["musicmap_similar"] = musicmap_data
    time.sleep(0.5)  # polite delay for music-map.com

    # Search Apple Music for the artist ID
    print(f"  Searching Apple Music catalog...")
    artist_id, matched_name = apple_client.search_artist(artist_name)
    time.sleep(API_RATE_LIMIT)

    if artist_id is None:
        print(f"  [SKIP] Artist not found on Apple Music: '{artist_name}'")
        result["musicmap_only"] = list(musicmap_data.keys())
        return result

    result["apple_id"] = artist_id
    result["apple_matched_name"] = matched_name

    # Fetch similar artists from Apple Music
    print(f"  Fetching Apple Music similar artists (ID: {artist_id})...")
    apple_similar = apple_client.get_similar_artists(artist_id)
    result["apple_similar"] = apple_similar
    time.sleep(API_RATE_LIMIT)

    # Compare: normalize names to lowercase for matching
    apple_names = {a["name"].strip().lower() for a in apple_similar}
    musicmap_names = set(musicmap_data.keys())  # already lowercase

    overlap = apple_names & musicmap_names
    apple_only = apple_names - musicmap_names
    musicmap_only = musicmap_names - apple_names

    result["overlap"] = sorted(overlap)
    result["apple_only"] = sorted(apple_only)
    result["musicmap_only"] = sorted(musicmap_only)

    return result


# ── Report Formatting ────────────────────────────────────
def print_report(results):
    """Print a formatted comparison report to stdout."""
    sep = "=" * 78
    thin_sep = "-" * 78

    print(f"\n{sep}")
    print(f"  APPLE MUSIC API vs MUSIC-MAP.COM — Similar Artists Comparison")
    print(f"{sep}\n")

    total_overlap = 0
    total_apple = 0
    total_musicmap = 0
    artists_with_apple_data = 0
    artists_with_musicmap_data = 0

    for r in results:
        print(f"\n{thin_sep}")
        artist_label = r["artist"]
        if r["apple_matched_name"] and r["apple_matched_name"].lower() != r["artist"].lower():
            artist_label += f"  (Apple: \"{r['apple_matched_name']}\")"
        print(f"  Artist: {artist_label}")
        if r["apple_id"]:
            print(f"  Apple Music ID: {r['apple_id']}")
        print(f"{thin_sep}")

        apple_count = len(r["apple_similar"])
        musicmap_count = len(r["musicmap_similar"])
        overlap_count = len(r["overlap"])

        if apple_count > 0:
            artists_with_apple_data += 1
        if musicmap_count > 0:
            artists_with_musicmap_data += 1

        total_apple += apple_count
        total_musicmap += musicmap_count
        total_overlap += overlap_count

        print(f"\n  Apple Music similar: {apple_count:>3}")
        print(f"  music-map.com similar: {musicmap_count:>3}")

        if apple_count == 0 and musicmap_count == 0:
            print(f"  [No similar artist data from either source]")
            continue

        if overlap_count > 0:
            pct_of_apple = (overlap_count / apple_count * 100) if apple_count else 0
            pct_of_musicmap = (overlap_count / musicmap_count * 100) if musicmap_count else 0
            print(f"  Overlap: {overlap_count:>3}  "
                  f"({pct_of_apple:.0f}% of Apple, {pct_of_musicmap:.0f}% of music-map)")
            print(f"\n  Overlapping artists:")
            for name in r["overlap"]:
                mm_score = r["musicmap_similar"].get(name, 0)
                print(f"    {name:<40} (music-map proximity: {mm_score:.2f})")
        else:
            print(f"  Overlap: 0  (no shared artists)")

        if r["apple_only"]:
            print(f"\n  Apple Music only ({len(r['apple_only'])}):")
            for name in r["apple_only"][:15]:
                print(f"    {name}")
            if len(r["apple_only"]) > 15:
                print(f"    ... and {len(r['apple_only']) - 15} more")

        if r["musicmap_only"]:
            print(f"\n  music-map.com only ({len(r['musicmap_only'])}):")
            for name in r["musicmap_only"][:15]:
                score = r["musicmap_similar"].get(name, 0)
                print(f"    {name:<40} (proximity: {score:.2f})")
            if len(r["musicmap_only"]) > 15:
                print(f"    ... and {len(r['musicmap_only']) - 15} more")

    # Summary
    print(f"\n{sep}")
    print(f"  SUMMARY")
    print(f"{sep}")
    print(f"  Artists sampled:             {len(results)}")
    print(f"  Artists with Apple data:     {artists_with_apple_data}")
    print(f"  Artists with music-map data: {artists_with_musicmap_data}")
    print(f"  Total Apple similar:         {total_apple}")
    print(f"  Total music-map similar:     {total_musicmap}")
    print(f"  Total overlap:               {total_overlap}")
    if total_apple > 0:
        print(f"  Overlap as % of Apple:       {total_overlap / total_apple * 100:.1f}%")
    if total_musicmap > 0:
        print(f"  Overlap as % of music-map:   {total_overlap / total_musicmap * 100:.1f}%")
    print(f"{sep}\n")


# ── Artist Sampling ──────────────────────────────────────
def sample_library_artists(count):
    """Read the user's Music library and return a random sample of artist names.

    Uses the XML library parser. Returns a list of artist names (original case
    is not available from XML — returns lowercase).
    """
    library_path = _resolve_library_path()
    if library_path is None:
        print("ERROR: Could not find Music Library XML.")
        print("       Export it: Music.app -> File -> Library -> Export Library...")
        sys.exit(1)

    library_artists, _ = parse_library(library_path)
    if not library_artists:
        print("ERROR: No loved/favorited artists found in library.")
        sys.exit(1)

    # Sort by loved-track count descending, then sample from top half
    # to bias toward artists the user cares most about
    sorted_artists = sorted(library_artists.items(), key=lambda x: x[1], reverse=True)
    top_half = sorted_artists[:max(len(sorted_artists) // 2, count)]
    sample = random.sample(top_half, min(count, len(top_half)))

    return [name for name, _ in sample]


# ── Main ─────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Compare similar artists: Apple Music API vs music-map.com"
    )
    parser.add_argument(
        "--count", type=int, default=SAMPLE_SIZE,
        help=f"Number of random artists to compare (default: {SAMPLE_SIZE})"
    )
    parser.add_argument(
        "--artists", type=str, default=None,
        help="Comma-separated list of artist names (overrides --count)"
    )
    args = parser.parse_args()

    # Load .env
    load_dotenv()

    # Read Apple Music API credentials
    key_id = os.environ.get("APPLE_MUSIC_KEY_ID", "").strip()
    team_id = os.environ.get("APPLE_MUSIC_TEAM_ID", "").strip()
    key_path = os.environ.get("APPLE_MUSIC_KEY_PATH", "").strip()

    if not key_id or not team_id or not key_path:
        print("ERROR: Apple Music API credentials not configured.")
        print("       Set APPLE_MUSIC_KEY_ID, APPLE_MUSIC_TEAM_ID, and")
        print("       APPLE_MUSIC_KEY_PATH in your .env file.")
        print("       See .env.example for details.")
        sys.exit(1)

    # Generate JWT token
    print("Generating Apple Music API token...")
    try:
        token = generate_apple_music_token(key_id, team_id, key_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    print("Token generated successfully.")

    # Initialize Apple Music client
    apple_client = AppleMusicClient(token)

    # Get artist list
    if args.artists:
        artist_names = [a.strip().lower() for a in args.artists.split(",") if a.strip()]
        print(f"\nComparing {len(artist_names)} specified artists...")
    else:
        print(f"\nSampling {args.count} artists from your library...")
        artist_names = sample_library_artists(args.count)

    print(f"Artists: {', '.join(artist_names)}\n")

    # Run comparisons
    results = []
    for i, artist in enumerate(artist_names, 1):
        print(f"\n[{i}/{len(artist_names)}] {artist}")
        result = compare_for_artist(artist, apple_client)
        results.append(result)

    # Print report
    print_report(results)

    # Save raw data for further analysis
    output_path = pathlib.Path(__file__).parent / "similarity_comparison.json"
    serializable = []
    for r in results:
        serializable.append({
            "artist": r["artist"],
            "apple_id": r["apple_id"],
            "apple_matched_name": r["apple_matched_name"],
            "apple_similar": r["apple_similar"],
            "musicmap_similar": r["musicmap_similar"],
            "overlap": r["overlap"],
            "apple_only": r["apple_only"],
            "musicmap_only": r["musicmap_only"],
        })
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False)
    print(f"Raw data saved to: {output_path}")


if __name__ == "__main__":
    main()
```

---

### Task 3: Write tests for JWT generation and API client

**Files:**
- Create: `tests/poc/test_compare_similarity.py`

- [ ] **Step 1: Create test file with unit tests**

```python
"""Tests for compare_similarity.py — Apple Music API POC."""

import json
import pathlib
import sys
import time
from unittest.mock import MagicMock, patch, mock_open

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
import compare_similarity as cs


# ── JWT Token Tests ───────────────────────────────────────

FAKE_P8_KEY = """-----BEGIN PRIVATE KEY-----
MIGTAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBHkwdwIBAQQg0hJCXqYCjkfU0bKy
cGGWl4JBKj7YfVjfQ6sSMJyqMcOgCgYIKoZIzj0DAQehRANCAAR7E4hh3vOvBfzz
OoWs8ynAGsMp2k7MnMCq6DL2VbTLRoFmGJ2YzTLEu6zBC3GJY1S8GmGJV6jqQ5SN
PAh1kJqG
-----END PRIVATE KEY-----"""


def test_generate_token_missing_key_id():
    """Raises ValueError when key_id is empty."""
    with pytest.raises(ValueError, match="APPLE_MUSIC_KEY_ID"):
        cs.generate_apple_music_token("", "TEAMID1234", "/fake/key.p8")


def test_generate_token_missing_team_id():
    """Raises ValueError when team_id is empty."""
    with pytest.raises(ValueError, match="APPLE_MUSIC_KEY_ID"):
        cs.generate_apple_music_token("KEYID12345", "", "/fake/key.p8")


def test_generate_token_missing_key_file():
    """Raises FileNotFoundError when .p8 file doesn't exist."""
    with pytest.raises(FileNotFoundError, match="private key not found"):
        cs.generate_apple_music_token("KEYID12345", "TEAMID1234", "/nonexistent/key.p8")


def test_generate_token_success(tmp_path):
    """Generates a valid JWT when given valid inputs."""
    key_file = tmp_path / "AuthKey_TEST.p8"
    key_file.write_text(FAKE_P8_KEY)

    token = cs.generate_apple_music_token("KEYID12345", "TEAMID1234", str(key_file))

    assert isinstance(token, str)
    assert len(token) > 50  # JWT tokens are long

    # Decode without verification to check claims
    import jwt as pyjwt
    decoded = pyjwt.decode(token, options={"verify_signature": False})
    assert decoded["iss"] == "TEAMID1234"
    assert "iat" in decoded
    assert "exp" in decoded
    assert decoded["exp"] - decoded["iat"] == cs.TOKEN_TTL


# ── Apple Music Client Tests ─────────────────────────────

def make_search_response(artist_name, artist_id):
    """Helper: build a mock Apple Music search response."""
    return {
        "results": {
            "artists": {
                "data": [
                    {
                        "id": artist_id,
                        "type": "artists",
                        "attributes": {"name": artist_name},
                    }
                ]
            }
        }
    }


def make_similar_response(artist_id, similar_list):
    """Helper: build a mock Apple Music similar-artists response."""
    similar_data = [
        {
            "id": sid,
            "type": "artists",
            "attributes": {"name": sname},
        }
        for sname, sid in similar_list
    ]
    return {
        "data": [
            {
                "id": artist_id,
                "type": "artists",
                "views": {
                    "similar-artists": {
                        "data": similar_data,
                    }
                },
            }
        ]
    }


def test_search_artist_exact_match():
    """search_artist returns the exact match when available."""
    client = cs.AppleMusicClient("fake-token")
    mock_resp = MagicMock()
    mock_resp.json.return_value = make_search_response("Radiohead", "123456")
    mock_resp.raise_for_status = MagicMock()

    with patch.object(client.session, "get", return_value=mock_resp):
        artist_id, name = client.search_artist("radiohead")

    assert artist_id == "123456"
    assert name == "Radiohead"


def test_search_artist_not_found():
    """search_artist returns (None, None) when no results."""
    client = cs.AppleMusicClient("fake-token")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": {"artists": {"data": []}}}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(client.session, "get", return_value=mock_resp):
        artist_id, name = client.search_artist("nonexistent_artist_xyz")

    assert artist_id is None
    assert name is None


def test_search_artist_api_error():
    """search_artist returns (None, None) on request failure."""
    client = cs.AppleMusicClient("fake-token")

    with patch.object(client.session, "get", side_effect=cs.requests.ConnectionError("fail")):
        artist_id, name = client.search_artist("radiohead")

    assert artist_id is None
    assert name is None


def test_get_similar_artists_success():
    """get_similar_artists returns list of similar artist dicts."""
    client = cs.AppleMusicClient("fake-token")
    similar = [("Thom Yorke", "111"), ("Atoms for Peace", "222")]
    mock_resp = MagicMock()
    mock_resp.json.return_value = make_similar_response("123456", similar)
    mock_resp.raise_for_status = MagicMock()

    with patch.object(client.session, "get", return_value=mock_resp):
        results = client.get_similar_artists("123456")

    assert len(results) == 2
    assert results[0]["name"] == "Thom Yorke"
    assert results[0]["id"] == "111"
    assert results[1]["name"] == "Atoms for Peace"


def test_get_similar_artists_empty():
    """get_similar_artists returns empty list when no similar artists."""
    client = cs.AppleMusicClient("fake-token")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": [{"id": "123", "views": {}}]}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(client.session, "get", return_value=mock_resp):
        results = client.get_similar_artists("123")

    assert results == []


# ── Comparison Logic Tests ───────────────────────────────

def test_compare_for_artist_both_sources():
    """compare_for_artist correctly identifies overlap and unique artists."""
    mock_client = MagicMock()
    mock_client.search_artist.return_value = ("999", "Test Artist")
    mock_client.get_similar_artists.return_value = [
        {"name": "Shared One", "id": "1"},
        {"name": "Apple Only", "id": "2"},
        {"name": "Shared Two", "id": "3"},
    ]

    musicmap_data = {
        "shared one": 0.9,
        "shared two": 0.5,
        "musicmap only": 0.3,
    }

    with patch.object(cs, "scrape_musicmap_requests", return_value=musicmap_data):
        with patch("time.sleep"):  # skip delays in tests
            result = cs.compare_for_artist("test artist", mock_client)

    assert result["apple_id"] == "999"
    assert set(result["overlap"]) == {"shared one", "shared two"}
    assert result["apple_only"] == ["apple only"]
    assert result["musicmap_only"] == ["musicmap only"]


def test_compare_for_artist_apple_not_found():
    """When Apple Music can't find the artist, all musicmap results are musicmap_only."""
    mock_client = MagicMock()
    mock_client.search_artist.return_value = (None, None)

    musicmap_data = {"similar one": 0.8, "similar two": 0.5}

    with patch.object(cs, "scrape_musicmap_requests", return_value=musicmap_data):
        with patch("time.sleep"):
            result = cs.compare_for_artist("unknown artist", mock_client)

    assert result["apple_id"] is None
    assert len(result["musicmap_only"]) == 2
    assert result["overlap"] == []
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/poc/test_compare_similarity.py -v`

---

### Task 4: Add `.gitignore` entry and verify end-to-end

**Files:**
- Modify: `.gitignore` (if it exists) — add `similarity_comparison.json` and `*.p8`

- [ ] **Step 1: Update `.gitignore`**

Add these lines to `.gitignore` to prevent committing sensitive or generated files:

```
# Apple Music API POC
*.p8
similarity_comparison.json
```

- [ ] **Step 2: Verify the script runs with `--help`**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python compare_similarity.py --help`

Expected output: usage information with `--count` and `--artists` flags.

- [ ] **Step 3: Verify credential error handling**

Run without credentials configured (temporarily unset env vars or use a clean env):

```bash
cd "/Users/brianhill/Scripts/Music Discovery" && \
    APPLE_MUSIC_KEY_ID= APPLE_MUSIC_TEAM_ID= APPLE_MUSIC_KEY_PATH= \
    python compare_similarity.py
```

Expected: graceful error message pointing to `.env.example`.

---

### Task 5: Manual integration test (requires real credentials)

This task is manual — skip if Apple Music API credentials are not yet configured.

- [ ] **Step 1: Configure credentials**

1. Go to https://developer.apple.com/account/resources/authkeys/list
2. Create a MusicKit key, download the `.p8` file
3. Set in `.env`:
   ```
   APPLE_MUSIC_KEY_ID=<your key ID>
   APPLE_MUSIC_TEAM_ID=<your team ID>
   APPLE_MUSIC_KEY_PATH=~/path/to/AuthKey_XXXXXXXX.p8
   ```

- [ ] **Step 2: Run with a small sample**

```bash
cd "/Users/brianhill/Scripts/Music Discovery" && python compare_similarity.py --count 3
```

Verify: Token generation succeeds, artist searches return results, similar-artists data is fetched, comparison report prints correctly.

- [ ] **Step 3: Run with specific artists for reproducible comparison**

```bash
cd "/Users/brianhill/Scripts/Music Discovery" && \
    python compare_similarity.py --artists "Radiohead,Bjork,Portishead,Massive Attack"
```

Verify: All four artists are found, report shows overlap and unique entries for each.
