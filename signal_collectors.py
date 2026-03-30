# signal_collectors.py
"""
Signal collectors for the wargaming experiment.

JXA-based collectors for play counts and playlist membership,
plus Apple Music API collectors for heavy rotation and recommendations.
"""

import json
import logging
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


def collect_ratings_jxa():
    """Read star ratings for ALL library tracks via JXA.

    Returns {artist_lowercase: {"avg_centered": float, "count": int}}.
    Centering: (star - 3) / 2 → 5★=+1.0, 4★=+0.5, 3★=0.0, 2★=-0.5, 1★=-1.0.
    Unrated tracks (rating=0) are treated as neutral (centered=0.0).
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
    var ratings = tracks.rating();
    for (var i = 0; i < count; i++) {
        result.push({artist: artists[i] || "", rating: ratings[i] || 0});
    }
}
JSON.stringify(result);
'''
    stdout, code = _run_jxa(script)
    if code != 0:
        raise RuntimeError(f"JXA ratings read failed (exit {code}): {stdout}")
    try:
        tracks = json.loads(stdout)
    except (json.JSONDecodeError, TypeError) as e:
        raise RuntimeError(f"Failed to parse JXA ratings output: {e}")

    artist_data = {}
    for t in tracks:
        artist = t.get("artist", "")
        if not isinstance(artist, str):
            continue
        artist = artist.strip().lower()
        if not artist:
            continue
        raw_rating = t.get("rating", 0) or 0
        if raw_rating == 0 or raw_rating % 20 != 0:
            centered = 0.0  # Unrated or computed rating → neutral
        else:
            stars = raw_rating // 20
            centered = (stars - 3) / 2
        if artist not in artist_data:
            artist_data[artist] = {"total": 0.0, "count": 0}
        artist_data[artist]["total"] += centered
        artist_data[artist]["count"] += 1

    return {
        a: {"avg_centered": d["total"] / d["count"], "count": d["count"]}
        for a, d in artist_data.items()
        if d["count"] > 0
    }


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
    """Fetch heavy rotation content from Apple Music API."""
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
    """Fetch personal recommendations from Apple Music API."""
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
