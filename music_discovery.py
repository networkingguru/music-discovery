# music_discovery.py
"""
Apple Music Discovery Tool
Reads loved/favorited artists from your Music library,
finds similar artists via music-map.com, and ranks new
artists by how many of your artists point to them.
"""

import argparse
import json
import logging
import math
import os
import re
import subprocess
import sys
import time
import traceback
import plistlib
import pathlib
import platform
import datetime
import uuid
import hashlib
import getpass
import requests
from bs4 import BeautifulSoup

# ── Path Resolution ────────────────────────────────────────
def _resolve_library_path(cli_override=None):
    """Resolve the Music Library XML path.
    Priority: CLI flag > platform auto-detect.
    Returns a pathlib.Path if found, or None if not found (with helpful log message)."""
    if cli_override:
        p = pathlib.Path(cli_override).expanduser().resolve()
        if p.exists():
            return p
        log.error(f"Library file not found: {p}")
        return None

    system = platform.system()
    if system == "Darwin":
        default = pathlib.Path.home() / "Music/Music/Music Library.xml"
        export_hint = 'Open Music.app → File → Library → Export Library…'
    elif system == "Windows":
        default = pathlib.Path.home() / "Music/iTunes/iTunes Music Library.xml"
        export_hint = 'Open iTunes → File → Library → Export Library…'
    else:
        log.error("Could not auto-detect library path on this platform.")
        log.error("Specify it manually: python music_discovery.py --library /path/to/Library.xml")
        return None

    if default.exists():
        return default

    log.error(f"Music Library not found at {default}")
    log.error(f"  {export_hint}")
    log.error("  Or specify the path manually: python music_discovery.py --library /path/to/Library.xml")
    return None


# ── Constants ──────────────────────────────────────────────
MUSICMAP_URL = "https://www.music-map.com/{}"
RATE_LIMIT   = 1.0  # seconds between requests

# Nav links to ignore when scraping music-map.com
SKIP_HREFS = {"", "/", "/about", "/contact", "/gnod"}

LASTFM_API_URL      = "http://ws.audioscrobbler.com/2.0/"
MUSICBRAINZ_API_URL = "https://musicbrainz.org/ws/2/artist/{}"
POPULAR_THRESHOLD   = 50_000
CLASSIC_YEAR        = 2006
TRACKS_PER_ARTIST   = 3
MAX_PLAYLIST_TRACKS = 500  # hard cap — abort if playlist exceeds this
MB_USER_AGENT       = "MusicDiscoveryTool/1.0 (https://github.com/networkingguru/music-discovery)"

# Artists/non-artists that slip through the listener-count filter due to missing
# or wrong Last.fm data. Names must be lowercase to match scored candidate names.
ARTIST_BLOCKLIST = {
    # Non-artists scraped from music-map.com (song titles, genres, etc.)
    "let her go", "say something", "riptide", "classic rock",
}
# User-managed blocklist: add artist names to blocklist.txt in the project root.
# See blocklist.txt for format details.

# Matches decade/era labels like "70s", "80's", "90's music" — not real artists
_DECADE_RE = re.compile(r"^\d0'?s(\s\w+)*$")

# Matches cover/karaoke tags like "(as made famous by Metallica)"
_COVER_RE = re.compile(r"as made famous by", re.IGNORECASE)

# Strip parentheticals, "- Live at …", and other suffixes for dedup comparison
_DEDUP_STRIP_RE = re.compile(r"\s*[\(\[].*?[\)\]]|\s*-\s.*$")

DEFAULT_CACHE_DIR = "~/.cache/music_discovery"

LOG_PATH = pathlib.Path(__file__).parent / "run.log"


def _setup_logging():
    """Configure logging to both console and run.log file.
    File gets full detail (DEBUG); console gets INFO and above."""
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # File handler — captures everything including tracebacks
    fh = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
    ))
    logger.addHandler(fh)

    # Console handler — INFO and above (user-facing output)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(ch)

    return logger


log = _setup_logging()


def load_dotenv(dotenv_path=None):
    """Load .env file into os.environ. Keys already in env are not overwritten.
    dotenv_path defaults to a .env file next to this script.
    Detects ENC: prefix on LASTFM_API_KEY and decrypts it.
    Prints a note if .env is missing and points to .env.example."""
    if dotenv_path is None:
        dotenv_path = pathlib.Path(__file__).parent / ".env"
    path = pathlib.Path(dotenv_path)
    if not path.exists():
        log.info(f"NOTE: No .env file found at {path}.")
        log.info("      Copy .env.example → .env and fill in your settings.")
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key   = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            # Decrypt ENC:-prefixed values for LASTFM_API_KEY
            if key == "LASTFM_API_KEY" and value.startswith("ENC:"):
                try:
                    value = decrypt_key(value[4:])
                    if not _validate_api_key(value):
                        log.warning("Stored key could not be decrypted (hardware change?).")
                        log.warning("         Please re-enter your API key.")
                        value = ""
                except Exception:
                    log.warning("Failed to decrypt stored API key.")
                    value = ""
            if key and key not in os.environ:
                os.environ[key] = value


def _get_machine_seed():
    """Return 32-byte SHA-256 hash of a stable hardware UUID.
    macOS: IOPlatformUUID via ioreg (stable across reboots).
    Windows: MachineGuid from the registry.
    Linux: /etc/machine-id.
    Returns None if no stable identifier can be found."""
    hw_uuid = None
    import platform
    system = platform.system()

    if system == "Darwin":
        try:
            result = subprocess.run(
                ["ioreg", "-d2", "-c", "IOPlatformExpertDevice"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if "IOPlatformUUID" in line:
                    hw_uuid = line.split('"')[-2]
                    break
        except Exception:
            pass

    elif system == "Windows":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography"
            ) as key:
                hw_uuid, _ = winreg.QueryValueEx(key, "MachineGuid")
        except Exception:
            pass

    elif system == "Linux":
        try:
            hw_uuid = pathlib.Path("/etc/machine-id").read_text().strip()
        except Exception:
            pass

    if hw_uuid:
        return hashlib.sha256(hw_uuid.encode()).digest()
    return None


def encrypt_key(plain):
    """XOR plain-text key against machine seed, return hex string.
    Raises RuntimeError if machine seed is unavailable."""
    seed = _get_machine_seed()
    if seed is None:
        raise RuntimeError("Cannot encrypt: no stable machine identifier")
    plain_bytes = plain.encode("utf-8")
    cipher = bytes(a ^ b for a, b in zip(plain_bytes, seed))
    return cipher.hex()


def decrypt_key(cipher_hex):
    """XOR hex-encoded cipher against machine seed, return plain text.
    Raises RuntimeError if machine seed is unavailable."""
    seed = _get_machine_seed()
    if seed is None:
        raise RuntimeError("Cannot decrypt: no stable machine identifier")
    cipher_bytes = bytes.fromhex(cipher_hex)
    plain = bytes(a ^ b for a, b in zip(cipher_bytes, seed))
    return plain.decode("utf-8")


def _validate_api_key(key):
    """Return True if key looks like a valid Last.fm API key (32-char hex)."""
    return bool(re.match(r"^[0-9a-fA-F]{32}$", key))


def _write_key_to_env(value, env_path=None):
    """Write LASTFM_API_KEY=<value> to .env file.
    Creates file if missing, appends if key absent, replaces if key exists."""
    if env_path is None:
        env_path = pathlib.Path(__file__).parent / ".env"
    env_path = pathlib.Path(env_path)

    key_line = f"LASTFM_API_KEY={value}\n"

    if not env_path.exists():
        env_path.write_text(key_line, encoding="utf-8")
        return

    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    found = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("LASTFM_API_KEY=") or stripped == "LASTFM_API_KEY":
            new_lines.append(key_line)
            found = True
        else:
            new_lines.append(line)
    if not found:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        new_lines.append(key_line)
    env_path.write_text("".join(new_lines), encoding="utf-8")


def prompt_for_api_key(env_path=None):
    """Interactive first-run prompt for the Last.fm API key.
    Validates, encrypts (if possible), writes to .env, returns plain key.
    Returns None if user skips (empty input) or after 3 failed attempts."""
    log.info("\n" + "=" * 60)
    log.info("  Last.fm API Key Setup")
    log.info("=" * 60)
    log.info("\nThis tool uses the Last.fm API to filter and enrich results.")
    log.info("You need a free API key for the best experience.\n")
    log.info("  1. Go to: https://www.last.fm/api/account/create")
    log.info("  2. Log in (or create a free account)")
    log.info("  3. Fill in an application name and description (anything works)")
    log.info("  4. Copy the 'API Key' shown on the next page\n")
    log.info("Press Enter with no input to skip (results won't be filtered as well).\n")

    for attempt in range(3):
        key = getpass.getpass("Enter your Last.fm API key: ").strip()
        if not key:
            log.info("\nSkipping Last.fm setup.")
            return None
        if _validate_api_key(key):
            seed = _get_machine_seed()
            if seed is not None:
                value = "ENC:" + encrypt_key(key)
            else:
                log.info("NOTE: Could not detect stable hardware ID.")
                log.info("      Key will be stored in plain text.")
                value = key
            _write_key_to_env(value, env_path)
            log.info("API key saved to .env successfully.\n")
            # Create .env.example if it doesn't exist
            example_path = pathlib.Path(__file__).parent / ".env.example"
            if not example_path.exists():
                example_path.write_text(
                    "# Last.fm API key (optional, recommended)\n"
                    "# Get yours at: https://www.last.fm/api/account/create\n"
                    "LASTFM_API_KEY=\n"
                    "\n"
                    "# Optional: override default cache/output directories\n"
                    "# CACHE_DIR=~/.cache/music_discovery\n"
                    "# OUTPUT_DIR=~/.cache/music_discovery\n",
                    encoding="utf-8",
                )
            return key
        remaining = 2 - attempt
        if remaining > 0:
            log.info(f"Invalid key (must be 32 hex characters). {remaining} attempt(s) left.")
        else:
            log.info("Invalid key. No attempts remaining.")
            log.info("Get your key at: https://www.last.fm/api/account/create")
    return None


def _build_paths():
    """Resolve CACHE_DIR and OUTPUT_DIR from env, create dirs, return path dict.
    Returns {"cache": Path, "filter_cache": Path, "output": Path}."""
    cache_dir  = pathlib.Path(
        os.environ.get("CACHE_DIR", DEFAULT_CACHE_DIR)
    ).expanduser().resolve()
    output_dir = pathlib.Path(
        os.environ.get("OUTPUT_DIR", DEFAULT_CACHE_DIR)  # same default as cache
    ).expanduser().resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    return {
        "cache":        cache_dir  / "music_map_cache.json",
        "filter_cache": cache_dir  / "filter_cache.json",
        "blocklist":    cache_dir  / "blocklist_cache.json",
        "top_tracks":   cache_dir  / "top_tracks_cache.json",
        "output":       output_dir / "music_discovery_results.txt",
        "playlist_xml": output_dir / "Music Discovery.xml",
    }


def parse_library(xml_path):
    """Parse Music Library XML, return {artist_name: loved_track_count} dict.
    Artists are lowercase. Only includes tracks that are Loved or Favorited."""
    try:
        with open(xml_path, "rb") as f:
            library = plistlib.load(f)
    except FileNotFoundError:
        log.error(f"Library file not found: {xml_path}")
        raise
    except Exception as e:
        log.error(f"Could not read library file: {e}")
        raise

    tracks = library.get("Tracks", {})
    counts = {}
    for track in tracks.values():
        if not isinstance(track, dict):
            continue
        if track.get("Loved") or track.get("Favorited"):
            artist = track.get("Artist", "")
            if not isinstance(artist, str):
                continue
            artist = artist.strip().lower()
            if artist:
                counts[artist] = counts.get(artist, 0) + 1
    return counts

def parse_md_playlist(xml_path):
    """Find the 'Music Discovery' playlist in the XML and return audit data.
    Returns (artist_set, total_tracks, unplayed_count) or None if no MD playlist.
    artist_set contains lowercased artist names from the playlist.
    A track is 'unplayed' if Play Count is 0 or absent."""
    try:
        with open(xml_path, "rb") as f:
            library = plistlib.load(f)
    except Exception:
        return None

    tracks_dict = library.get("Tracks", {})
    playlists = library.get("Playlists", [])

    md_playlist = None
    for pl in playlists:
        if pl.get("Name") == "Music Discovery":
            md_playlist = pl
            break
    if md_playlist is None:
        return None

    items = md_playlist.get("Playlist Items", [])
    if not items:
        return None

    artists = set()
    unplayed = 0
    total = 0
    for item in items:
        track_id = str(item.get("Track ID", ""))
        track = tracks_dict.get(track_id)
        if track is None:
            continue
        total += 1
        artist = track.get("Artist", "").strip().lower()
        if artist:
            artists.add(artist)
        if track.get("Play Count", 0) == 0:
            unplayed += 1

    if total == 0:
        return None

    return artists, total, unplayed

def audit_md_playlist(playlist_artists, library_artists, existing_blocklist,
                      total, unplayed, interactive=True):
    """Check MD playlist artists against loved artists. Return set of artists to blocklist.
    - playlist_artists: set of lowercased artist names from the MD playlist.
    - library_artists: dict {artist: loved_count} from parse_library (only loved artists).
    - existing_blocklist: set of already-blocklisted names (won't be re-added).
    - total: total tracks in MD playlist.
    - unplayed: count of tracks with play count 0.
    - interactive: if True and >25% unplayed, prompt user. If False, skip blocklisting.
    Returns set of new artist names to add to blocklist."""
    unplayed_pct = (unplayed / total) * 100 if total > 0 else 0
    log.info(f"Music Discovery playlist: {total} tracks, {unplayed} unplayed "
             f"({unplayed_pct:.0f}%).")

    if unplayed_pct > 25:
        if not interactive:
            log.info("Non-interactive mode — skipping playlist audit blocklisting.")
            return set()
        answer = input(
            f"Over 25% of your Music Discovery playlist is unplayed "
            f"({unplayed}/{total}). Blocklist unheard artists anyway? (y/n): "
        ).strip().lower()
        if answer != 'y':
            log.info("Skipping playlist audit blocklisting.")
            return set()

    rejected = set()
    for artist in playlist_artists:
        if artist in library_artists:
            continue
        if artist in existing_blocklist:
            continue
        rejected.add(artist)

    if rejected:
        log.info(f"Blocklisting {len(rejected)} rejected artist(s) from playlist audit: "
                 f"{sorted(rejected)}")
    else:
        log.info("No new artists to blocklist from playlist audit.")

    return rejected

def scrape_musicmap_requests(artist):
    """Fetch similar artists from music-map.com using requests.
    Returns {artist_name: proximity_score} dict (0.0–1.0), or {} on failure.
    Proximity uses link order as proxy (first = 1.0); Playwright gives true coordinates."""
    slug = artist.lower().replace(" ", "+")
    url  = MUSICMAP_URL.format(slug)
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    except Exception as e:
        log.debug(f"Scrape request failed for '{artist}': {e}")
        return {}

    if resp.status_code != 200:
        log.debug(f"Scrape got status {resp.status_code} for '{artist}'")
        return {}

    soup  = BeautifulSoup(resp.text, "html.parser")
    names = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href in SKIP_HREFS or not href.startswith("/"):
            continue
        name = a.get_text(strip=True).lower()
        if name:
            names.append(name)

    total = len(names)
    if total == 0:
        return {}
    return {
        name: 1.0 - (i / (total - 1)) if total > 1 else 1.0
        for i, name in enumerate(names)
    }

def scrape_musicmap_playwright(artist):
    """Fetch similar artists using headless browser with coordinate-based proximity.
    Returns {artist_name: proximity_score} dict (0.0–1.0), or {} on failure.
    Proximity = 1 - (distance_from_viewport_center / max_distance), normalized 0–1."""
    import math as _math
    from playwright.sync_api import sync_playwright
    slug = artist.lower().replace(" ", "+")
    url  = MUSICMAP_URL.format(slug)
    skip = SKIP_HREFS | {"info", "about", "contact", "gnod"}
    data = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page    = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(url, timeout=20000)
            page.wait_for_load_state("networkidle", timeout=15000)
            viewport = page.viewport_size
            cx = viewport["width"] / 2
            cy = viewport["height"] / 2
            links = page.query_selector_all("a[href]")
            for link in links:
                href = (link.get_attribute("href") or "").strip()
                if not href or href.startswith("http") or href.lstrip("/") in skip:
                    continue
                name = (link.text_content() or "").strip().lower()
                if not name or name == "?":
                    continue
                box = link.bounding_box()
                if box is None:
                    continue
                lx = box["x"] + box["width"] / 2
                ly = box["y"] + box["height"] / 2
                dist = _math.sqrt((lx - cx)**2 + (ly - cy)**2)
                data.append((name, dist))
            browser.close()
    except Exception as e:
        log.warning(f"Playwright error for '{artist}': {e}")

    if not data:
        return {}
    max_dist = max(d for _, d in data)
    if max_dist == 0:
        return {name: 1.0 for name, _ in data}
    return {name: 1.0 - (dist / max_dist) for name, dist in data}

def detect_scraper():
    """Returns the scrape function to use. Tests Plan A; falls back to Plan B."""
    log.info("Detecting scraper method...")
    result = scrape_musicmap_requests("radiohead")
    if len(result) > 2:
        log.info(f"  Plan A (requests) works — got {len(result)} artists for test query.")
        return scrape_musicmap_requests
    log.info("  Plan A insufficient. Using Plan B (playwright headless browser).")
    return scrape_musicmap_playwright

def load_cache(cache_path):
    """Load scrape cache from JSON file. Returns {} if file doesn't exist or is corrupt."""
    path = pathlib.Path(cache_path)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        log.warning(f"Cache file is corrupt ({e}). Starting with empty cache.")
        return {}

def save_cache(cache, cache_path):
    """Write entire cache to JSON file (overwrites). Called after each artist."""
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def load_blocklist(path):
    """Load file-based blocklist. Returns a set of lowercase names."""
    path = pathlib.Path(path)
    if not path.exists():
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return set(json.load(f).get("blocked", []))
    except (json.JSONDecodeError, KeyError):
        return set()

def save_blocklist(blocked_set, path):
    """Persist file-based blocklist to JSON (sorted for readability)."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"blocked": sorted(blocked_set)}, f, ensure_ascii=False, indent=2)

def load_user_blocklist(path):
    """Load a plain-text blocklist file (one artist per line).
    Blank lines and lines starting with # are ignored.
    Names are lowercased for case-insensitive matching.
    Returns an empty set if file does not exist."""
    path = pathlib.Path(path)
    if not path.exists():
        return set()
    names = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                names.add(line.lower())
    return names

def detect_blocklist_candidates(scored, filter_cache):
    """Return names that are almost certainly non-artists, to auto-add to the blocklist.
    Only flags entries still {} in filter_cache after the re-fetch pass — meaning
    Last.fm found nothing for them even after retry, which is a strong signal they
    are genre tags, song titles, or other music-map noise rather than real artists."""
    return {name for _, name in scored if not filter_cache.get(name)}

def stale_cache_keys(cache):
    """Return list of artist keys whose cached value is a flat list (old format).
    These entries need to be re-scraped to produce proximity-score dicts."""
    return [k for k, v in cache.items() if isinstance(v, list)]

def fetch_filter_data(artist, api_key):
    """Fetch Last.fm listener count and MusicBrainz debut year for an artist.
    Uses artist.search first to resolve the canonical name, then artist.getInfo
    for the MBID, then MusicBrainz for the debut year.
    Returns {"listeners": int, "debut_year": int|None}, or {} on any failure.
    Never raises — network errors and missing data return {} or None gracefully."""
    try:
        # Step 1: resolve canonical name via search
        canonical = artist
        search_resp = requests.get(LASTFM_API_URL, timeout=10, params={
            "method":  "artist.search",
            "artist":  artist,
            "api_key": api_key,
            "format":  "json",
            "limit":   1,
        })
        if search_resp.status_code == 200:
            matches = (search_resp.json()
                       .get("results", {})
                       .get("artistmatches", {})
                       .get("artist", []))
            if matches:
                canonical = matches[0].get("name", artist)

        # Step 2: get listener count and MBID via getInfo
        resp = requests.get(LASTFM_API_URL, timeout=10, params={
            "method":  "artist.getInfo",
            "artist":  canonical,
            "api_key": api_key,
            "format":  "json",
        })
        if resp.status_code != 200:
            return {}
        data      = resp.json().get("artist", {})
        listeners = int(data.get("stats", {}).get("listeners", 0))
        mbid      = (data.get("mbid") or "").strip()

        # Step 3: get debut year from MusicBrainz
        debut_year = None
        if mbid:
            mb_resp = requests.get(
                MUSICBRAINZ_API_URL.format(mbid),
                timeout=10,
                headers={"User-Agent": MB_USER_AGENT},
                params={"fmt": "json"},
            )
            if mb_resp.status_code == 200:
                begin = (mb_resp.json().get("life-span", {}).get("begin") or "").strip()
                if begin:
                    debut_year = int(begin[:4])

        return {"listeners": listeners, "debut_year": debut_year}
    except Exception as e:
        log.debug(f"fetch_filter_data failed for '{artist}': {e}")
        return {}

def fetch_top_tracks(artist, api_key):
    """Fetch top 10 tracks for an artist from Last.fm.
    Returns list of {"name": str, "artist": str}, or [] on failure."""
    try:
        resp = requests.get(LASTFM_API_URL, timeout=10, params={
            "method":  "artist.getTopTracks",
            "artist":  artist,
            "api_key": api_key,
            "format":  "json",
            "limit":   TRACKS_PER_ARTIST,
        })
        if resp.status_code != 200:
            return []
        tracks = resp.json().get("toptracks", {}).get("track", [])
        return [
            {"name": t["name"], "artist": t["artist"]["name"]}
            for t in tracks
            if t.get("name")
        ]
    except Exception as e:
        log.debug(f"fetch_top_tracks failed for '{artist}': {e}")
        return []


ITUNES_SEARCH_URL = "https://itunes.apple.com/search"


def _applescript_escape(s):
    """Escape a string for safe embedding in AppleScript string literals.
    Handles backslashes, double quotes, and other problematic characters."""
    s = s.replace("\\", "\\\\")
    s = s.replace('"', '\\"')
    return s


def _run_applescript(script):
    """Run an AppleScript via osascript. Returns (stdout, returncode)."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        raise RuntimeError("osascript timed out after 30 seconds")


def _run_jxa(script):
    """Run a JXA (JavaScript for Automation) script. Returns (stdout, returncode)."""
    try:
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        raise RuntimeError("osascript (JXA) timed out after 30 seconds")


def search_itunes(artist, track_name):
    """Search the iTunes/Apple Music catalog for a track.
    Returns the store track ID (str) or None if not found.
    Verifies the artist name matches to avoid returning wrong tracks.
    Free API — no key required."""
    try:
        resp = requests.get(ITUNES_SEARCH_URL, timeout=10, params={
            "term":  f"{artist} {track_name}",
            "media": "music",
            "limit": 10,
        })
        if resp.status_code != 200:
            return None
        results = resp.json().get("results", [])
        artist_lower = artist.strip().lower()
        for r in results:
            result_artist = r.get("artistName", "").strip().lower()
            if result_artist == artist_lower:
                return str(r["trackId"])
        # Fallback: fuzzy match (one name contains the other)
        for r in results:
            result_artist = r.get("artistName", "").strip().lower()
            if artist_lower in result_artist or result_artist in artist_lower:
                return str(r["trackId"])
        return None
    except Exception as e:
        log.debug(f"search_itunes failed for '{artist} - {track_name}': {e}")
        return None


def setup_playlist():
    """Create or clear the 'Music Discovery' playlist.
    If the existing playlist has more than MAX_PLAYLIST_TRACKS, deletes the
    whole playlist and creates a fresh one (avoids beachballing Music.app
    on large track-delete operations).
    Verifies the playlist is empty before returning.
    Returns True on success, False on failure."""

    # Step 1: Check if playlist exists and how big it is
    count_script = '''
tell application "Music"
    if (exists user playlist "Music Discovery") then
        return count of tracks of user playlist "Music Discovery"
    else
        return -1
    end if
end tell
'''
    out, code = _run_applescript(count_script)
    if code != 0:
        log.error("Could not check for existing playlist.")
        return False

    try:
        track_count = int(out)
    except ValueError:
        log.error(f"Unexpected response checking playlist: {out}")
        return False

    # Step 2: Handle based on size
    if track_count == -1:
        # Playlist doesn't exist — create it
        _, code = _run_applescript('''
tell application "Music"
    make new user playlist with properties {name:"Music Discovery"}
end tell
''')
        return code == 0

    if track_count > MAX_PLAYLIST_TRACKS:
        # Too large to clear safely — delete the whole playlist and recreate
        log.info(f"Existing playlist has {track_count} tracks — deleting and recreating.")
        _, code = _run_applescript('''
tell application "Music"
    delete user playlist "Music Discovery"
end tell
''')
        if code != 0:
            log.error("Could not delete oversized playlist.")
            return False
        time.sleep(1)
        _, code = _run_applescript('''
tell application "Music"
    make new user playlist with properties {name:"Music Discovery"}
end tell
''')
        return code == 0

    if track_count > 0:
        # Small enough to clear normally
        _, code = _run_applescript('''
tell application "Music"
    delete tracks of user playlist "Music Discovery"
end tell
''')
        if code != 0:
            log.error("Could not clear playlist tracks.")
            return False

    # Step 3: Verify the playlist is empty
    out, code = _run_applescript(count_script)
    if code != 0:
        log.error("Could not verify playlist state after clearing.")
        return False
    try:
        final_count = int(out)
    except ValueError:
        log.error(f"Unexpected response verifying playlist: {out}")
        return False
    if final_count > 0:
        log.error(f"Playlist still has {final_count} tracks after clearing — aborting.")
        return False
    return True


def _play_store_track(store_id):
    """Use MediaPlayer framework via JXA to play a catalog track by store ID.
    This makes the track visible to Music.app as the current track."""
    script = f'''
ObjC.import("MediaPlayer");
ObjC.import("Foundation");
var player = $.MPMusicPlayerController.systemMusicPlayer;
var ids = $.NSArray.arrayWithObject($("{store_id}"));
var descriptor = $.MPMusicPlayerStoreQueueDescriptor.alloc.initWithStoreIDs(ids);
player.setQueueWithDescriptor(descriptor);
player.prepareToPlay;
player.play;
"ok";
'''
    out, code = _run_jxa(script)
    if code != 0:
        raise RuntimeError(f"JXA MediaPlayer failed (code {code})")
    return out == "ok"


def _stop_playback():
    """Stop the system music player."""
    script = '''
ObjC.import("MediaPlayer");
var player = $.MPMusicPlayerController.systemMusicPlayer;
player.stop;
"ok";
'''
    _run_jxa(script)


def add_track_to_playlist(artist, track_name):
    """Search Apple Music catalog for a track, add it to the user's library,
    then add it to the 'Music Discovery' playlist.
    Uses: iTunes Search API → MediaPlayer framework → AppleScript.
    Returns True if added, False if not found or already in playlist."""
    safe_artist = _applescript_escape(artist)
    safe_track = _applescript_escape(track_name)

    # Step 0: Check if track is already in the playlist (dedup)
    dedup_script = f'''
tell application "Music"
    try
        set sr to search user playlist "Music Discovery" for "{safe_track}"
        repeat with t in sr
            if artist of t is "{safe_artist}" then
                return "already_exists"
            end if
        end repeat
        return "not_found"
    on error
        return "not_found"
    end try
end tell
'''
    out, code = _run_applescript(dedup_script)
    if out == "already_exists":
        log.debug(f"  Skipping duplicate: {artist} — {track_name}")
        return True  # already there, count as success

    # Step 1: Find the track on Apple Music (free API, no key)
    store_id = search_itunes(artist, track_name)
    if not store_id:
        return False

    # Step 2: Snapshot current track before playing (to detect stale playback)
    snapshot_script = '''
tell application "Music"
    try
        set ct to current track
        return (name of ct) & "|||" & (artist of ct)
    on error
        return ""
    end try
end tell
'''
    prev_track, _ = _run_applescript(snapshot_script)

    # Step 3: Play the track via MediaPlayer (makes it visible to Music.app)
    _play_store_track(store_id)

    # Step 4: Poll until current track changes (replaces hardcoded sleep)
    poll_script = '''
tell application "Music"
    try
        set ct to current track
        return (name of ct) & "|||" & (artist of ct)
    on error
        return ""
    end try
end tell
'''
    for _ in range(10):
        time.sleep(0.5)
        out, _ = _run_applescript(poll_script)
        if out and out != prev_track:
            break
    else:
        log.debug(f"  Track did not change — skipping: {artist} — {track_name}")
        return False

    # Step 5: Add current track to library, search for library copy, add to playlist
    script = f'''
tell application "Music"
    try
        set ct to current track
        set trackName to name of ct
        set trackArtist to artist of ct
        duplicate ct to source "Library"
        delay 1
        set sr to search library playlist 1 for trackName
        repeat with t in sr
            if artist of t is trackArtist then
                duplicate t to user playlist "Music Discovery"
                return "ok"
            end if
        end repeat
        return "notfound_in_library"
    on error e
        return "error: " & e
    end try
end tell
'''
    out, code = _run_applescript(script)
    if code != 0:
        raise RuntimeError(f"osascript failed (code {code})")
    return out == "ok"


def write_playlist_xml(tracks, xml_path):
    """Write an Apple-compatible XML playlist plist that Music.app can import.
    tracks: list of {"name": str, "artist": str}"""
    track_dict = {}
    playlist_items = []
    for i, t in enumerate(tracks, start=1):
        track_id = i * 100
        track_dict[str(track_id)] = {
            "Track ID": track_id,
            "Name":     t["name"],
            "Artist":   t["artist"],
            "Kind":     "Apple Music AAC audio file",
        }
        playlist_items.append({"Track ID": track_id})

    plist_data = {
        "Major Version": 1,
        "Minor Version": 1,
        "Application Version": "1.0",
        "Tracks": track_dict,
        "Playlists": [{
            "Name":           "Music Discovery",
            "Playlist ID":    1,
            "Playlist Items": playlist_items,
        }],
    }
    with open(xml_path, "wb") as f:
        plistlib.dump(plist_data, f, fmt=plistlib.FMT_XML)


def _normalize_track_name(name):
    """Normalize a track name for deduplication: lowercase, strip parentheticals/suffixes."""
    return _DEDUP_STRIP_RE.sub("", name).strip().lower()


def build_playlist(ranked, api_key, paths, xml_only=False):
    """Fetch top tracks for top-50 artists, then build an Apple Music playlist."""
    top_artists = [name for _, name in ranked[:50]]
    if not top_artists:
        log.info("No artists in results — skipping playlist generation.")
        return True, []

    # ── Load top-tracks cache ──────────────────────────────
    top_tracks_cache = load_cache(paths["top_tracks"])

    # ── Fetch missing artists ──────────────────────────────
    missing = [a for a in top_artists if a not in top_tracks_cache]
    if missing:
        log.info(f"\nFetching top tracks for {len(missing)} artists (1 req/sec)...")
        for artist in missing:
            tracks = fetch_top_tracks(artist, api_key)
            top_tracks_cache[artist] = tracks
            save_cache(top_tracks_cache, paths["top_tracks"])
            time.sleep(RATE_LIMIT)

    # ── Flatten track list (filter covers, deduplicate) ─────
    all_tracks = []
    seen_names = set()
    covers_skipped = 0
    dupes_skipped = 0
    for artist in top_artists:
        for track in top_tracks_cache.get(artist, []):
            if _COVER_RE.search(track["name"]):
                covers_skipped += 1
                continue
            norm = _normalize_track_name(track["name"])
            if norm in seen_names:
                dupes_skipped += 1
                continue
            seen_names.add(norm)
            all_tracks.append(track)
    if covers_skipped or dupes_skipped:
        log.info(f"Filtered {covers_skipped} cover versions and {dupes_skipped} duplicate songs.")

    if xml_only:
        return True, all_tracks

    # ── Stage 1: setup playlist ────────────────────────────
    log.info("\nSetting up 'Music Discovery' playlist in Music.app...")
    if not setup_playlist():
        log.error("Could not create/clear playlist — aborting playlist build.")
        return False, all_tracks

    # ── Stage 2: search catalog and add tracks ─────────────
    log.info(f"Adding tracks to playlist ({len(all_tracks)} tracks across {len(top_artists)} artists)...")
    log.info("(Using iTunes Search API + MediaPlayer framework — no extra API key needed)")
    added = 0
    skipped = 0
    attempted = 0
    for i, artist in enumerate(top_artists, 1):
        artist_tracks = [t for t in all_tracks if t["artist"].strip().lower() == artist]
        if not artist_tracks:
            continue
        log.info(f"[{i}/{len(top_artists)}] Adding tracks for: {artist}")
        for track in artist_tracks:
            if added >= MAX_PLAYLIST_TRACKS:
                log.info(f"\nHard cap reached ({MAX_PLAYLIST_TRACKS} tracks). Stopping.")
                break
            attempted += 1
            try:
                if add_track_to_playlist(track["artist"], track["name"]):
                    added += 1
                else:
                    skipped += 1
                    log.info(f"  Not found: {track['artist']} — {track['name']}")
            except RuntimeError as e:
                log.error(f"  Error adding track: {e}")
                skipped += 1
        if added >= MAX_PLAYLIST_TRACKS:
            break

    # Stop playback so the user isn't left listening to the last track
    _stop_playback()

    log.info(f"\nPlaylist 'Music Discovery' created with {added}/{attempted} tracks"
             f" ({skipped} not found on Apple Music).")
    return True, all_tracks


def filter_candidates(scored, filter_cache, file_blocklist=frozenset()):
    """Remove candidates that are well-known artists the user likely already knows.
    Exclusion rules (any one is sufficient):
      1. Name is in ARTIST_BLOCKLIST (hardcoded) or file_blocklist (auto-detected).
      2. Name matches a decade/era pattern (e.g. "70s", "80's music").
      3. listeners > POPULAR_THRESHOLD AND debut_year <= CLASSIC_YEAR.
    If listener/debut values are missing, only rules 1–2 apply.
    scored: list of (score, name) tuples.
    filter_cache: {artist: {"listeners": int, "debut_year": int|None}} dict.
    file_blocklist: set of lowercase names from blocklist_cache.json."""
    combined = ARTIST_BLOCKLIST | file_blocklist
    result = []
    for score, name in scored:
        if name in combined:
            continue
        if _DECADE_RE.match(name):
            continue
        data       = filter_cache.get(name, {})
        listeners  = data.get("listeners")
        debut_year = data.get("debut_year")
        if (listeners is not None and listeners > POPULAR_THRESHOLD
                and debut_year is not None and debut_year <= CLASSIC_YEAR):
            continue
        result.append((score, name))
    return result

def score_artists(cache, library_artists):
    """Score non-library candidates using weighted proximity formula.
    score(candidate) = Σ log(loved_count[i] + 1) × proximity(i, candidate)
    library_artists: {artist: loved_count} dict from parse_library().
    Returns list of (score, artist_name) sorted descending."""
    library_set = set(library_artists.keys())
    scores = {}
    for lib_artist, similar in cache.items():
        if not isinstance(similar, dict):
            continue  # skip stale flat-list entries
        weight = math.log(library_artists.get(lib_artist, 1) + 1) ** 0.5
        for candidate, proximity in similar.items():
            if candidate not in library_set:
                scores[candidate] = scores.get(candidate, 0.0) + weight * proximity
    return sorted(((v, k) for k, v in scores.items()), key=lambda x: x[0], reverse=True)

def write_output(ranked, library_count, output_path):
    """Write full ranked list to file and top-50 summary to terminal."""
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    header = (
        f"Music Discovery Results — {date_str}\n"
        f"Library artists: {library_count}\n"
        f"New artists found: {len(ranked)}\n"
        f"{'─' * 50}\n"
    )
    lines = [f"{score:>9.3f}  {name}" for score, name in ranked]

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(lines))

    log.info("\n=== Top New Artists To Explore ===")
    for line in lines[:50]:
        log.info(line)
    if len(ranked) > 50:
        log.info(f"\n... and {len(ranked) - 50} more.")
    log.info(f"\nFull results saved to: {output_path}")

def main():
    # ── 0. Load config ─────────────────────────────────────
    parser = argparse.ArgumentParser(description="Apple Music Discovery Tool")
    parser.add_argument(
        "--playlist", action="store_true",
        help="After discovery, fetch top tracks and build an Apple Music playlist.",
    )
    parser.add_argument(
        "--library", type=str, default=None,
        help="Path to Music Library XML file (auto-detected if omitted).",
    )
    args = parser.parse_args()

    load_dotenv()
    paths = _build_paths()

    # ── 1. Parse library ───────────────────────────────────
    library_path = _resolve_library_path(args.library)
    if library_path is None:
        return

    log.info(f"Reading library: {library_path}")

    api_key = os.environ.get("LASTFM_API_KEY", "").strip()
    if not api_key:
        api_key = prompt_for_api_key()
        # api_key is None if user skipped or exhausted attempts

    if not api_key:
        log.info("\nRunning without Last.fm — results will include well-known artists")
        log.info("that would normally be filtered out.\n")

    library_artists = parse_library(library_path)
    log.info(f"Found {len(library_artists)} unique loved/favorited artists.\n")

    # ── 2. Load caches ─────────────────────────────────────
    cache        = load_cache(paths["cache"])
    filter_cache = load_cache(paths["filter_cache"]) if api_key else {}
    file_blocklist = load_blocklist(paths["blocklist"])
    user_blocklist_path = pathlib.Path(__file__).parent / "blocklist.txt"
    user_blocklist = load_user_blocklist(user_blocklist_path)
    file_blocklist |= user_blocklist

    # ── 2b. Audit previous Music Discovery playlist ────────
    md_audit = parse_md_playlist(library_path)
    if md_audit is not None:
        md_artists, md_total, md_unplayed = md_audit
        interactive = sys.stdin.isatty()
        newly_rejected = audit_md_playlist(
            md_artists, library_artists, file_blocklist,
            total=md_total, unplayed=md_unplayed, interactive=interactive,
        )
        if newly_rejected:
            file_blocklist |= newly_rejected
            save_blocklist(file_blocklist, paths["blocklist"])
            log.info(f"Saved {len(newly_rejected)} rejected artist(s) to blocklist.")

    already_done = len(cache)
    if already_done:
        log.info(f"Loaded scrape cache: {already_done} artists.")

    # ── 3. Re-scrape stale entries ─────────────────────────
    stale = stale_cache_keys(cache)
    if stale:
        log.info(f"Re-scraping {len(stale)} stale cache entries (format upgrade)...")
        for k in stale:
            del cache[k]
        save_cache(cache, paths["cache"])

    # ── 4. Scrape missing artists ──────────────────────────
    to_scrape = [a for a in library_artists if a not in cache]
    total     = len(library_artists)
    done      = len(cache)

    if to_scrape:
        scrape = detect_scraper()
        log.info(f"\nScraping {len(to_scrape)} artists (1 req/sec)...\n")
        for artist in to_scrape:
            done += 1
            log.info(f"[{done}/{total}] Scraping: {artist}")
            similar = scrape(artist)
            cache[artist] = similar
            save_cache(cache, paths["cache"])
            time.sleep(RATE_LIMIT)
    else:
        log.info("All artists already cached — skipping scrape.\n")

    # ── 5. Score ───────────────────────────────────────────
    log.info("\nScoring candidates...")
    scored = score_artists(cache, library_artists)

    # ── 6. Fetch filter data for new candidates ────────────
    if api_key:
        candidates     = [name for _, name in scored]
        new_candidates = [c for c in candidates if not filter_cache.get(c)]
        if new_candidates:
            log.info(f"Fetching filter data for {len(new_candidates)} candidates...")
            for i, candidate in enumerate(new_candidates, 1):
                if i % 50 == 0:
                    log.info(f"  [{i}/{len(new_candidates)}]")
                data = fetch_filter_data(candidate, api_key)
                filter_cache[candidate] = data
                save_cache(filter_cache, paths["filter_cache"])
                time.sleep(RATE_LIMIT)

        # ── 6b. Auto-detect and persist new blocklist entries ──
        new_blocked = detect_blocklist_candidates(scored, filter_cache)
        new_blocked -= ARTIST_BLOCKLIST  # don't duplicate hardcoded entries
        new_blocked -= user_blocklist    # don't duplicate user blocklist entries
        new_blocked -= file_blocklist    # don't re-add already-known entries
        if new_blocked:
            log.info(f"Auto-blocking {len(new_blocked)} non-artist entries: {sorted(new_blocked)}")
            file_blocklist |= new_blocked
            save_blocklist(file_blocklist, paths["blocklist"])
            # Purge newly blocked artists from top-tracks cache to prevent bloat
            top_tracks_cache = load_cache(paths["top_tracks"])
            purged = [a for a in new_blocked if a in top_tracks_cache]
            if purged:
                for a in purged:
                    del top_tracks_cache[a]
                save_cache(top_tracks_cache, paths["top_tracks"])
                log.info(f"Purged {len(purged)} blocked artist(s) from top_tracks_cache.")

    # ── 7. Filter and output ───────────────────────────────
    log.info("\nFiltering and writing results...")
    ranked = filter_candidates(scored, filter_cache, file_blocklist)
    write_output(ranked, len(library_artists), paths["output"])

    # ── 8. Build playlist (optional) ───────────────────────
    if args.playlist:
        if not api_key:
            log.info("\nPlaylist building requires a Last.fm API key. Skipping.")
        elif platform.system() == "Darwin":
            success, all_tracks = build_playlist(ranked, api_key, paths)
            if not success and all_tracks:
                log.info("\nFalling back to XML playlist export...")
                write_playlist_xml(all_tracks, paths["playlist_xml"])
                log.info(f"Import {paths['playlist_xml']} in Music.app via "
                         f"File → Library → Import Playlist.")
        else:
            # Windows (or other non-macOS): XML-only export
            log.info("\nBuilding XML playlist for import into iTunes...")
            _, all_tracks = build_playlist(ranked, api_key, paths,
                                           xml_only=True)
            if all_tracks:
                write_playlist_xml(all_tracks, paths["playlist_xml"])
                log.info(f"\nPlaylist saved to: {paths['playlist_xml']}")
                log.info("Import it in iTunes via File → Library → Import Playlist.")
            else:
                log.info("No tracks found — skipping playlist generation.")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.error("FATAL: Unhandled exception — full traceback below")
        log.error(traceback.format_exc())
        sys.exit(1)
