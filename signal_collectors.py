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
