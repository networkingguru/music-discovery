import os
import subprocess
import sys
import pathlib
import plistlib
import tempfile
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import music_discovery as md

SAMPLE_PLIST = {
    "Tracks": {
        "1": {"Artist": "Tom Waits",    "Loved": True},
        "2": {"Artist": "Radiohead",    "Favorited": True},
        "3": {"Artist": "Tom Waits",    "Loved": True},   # duplicate
        "4": {"Artist": "Coldplay",     "Name": "Yellow"}, # not loved/favorited
        "5": {"Name": "Instrumental"},                      # no artist key
    }
}

def write_temp_plist(data):
    """Write plist to a temp file, return the path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".xml", delete=False)
    tmp.write(plistlib.dumps(data))
    tmp.close()
    return tmp.name

def test_parse_library_loved():
    path = write_temp_plist({"Tracks": {"1": {"Artist": "Tom Waits", "Loved": True}}})
    result = md.parse_library(path)
    assert "tom waits" in result

def test_parse_library_favorited():
    path = write_temp_plist({"Tracks": {"1": {"Artist": "Radiohead", "Favorited": True}}})
    result = md.parse_library(path)
    assert "radiohead" in result

def test_parse_library_deduplicates():
    path = write_temp_plist(SAMPLE_PLIST)
    result = md.parse_library(path)
    assert list(result.keys()).count("tom waits") == 1

def test_parse_library_excludes_unloved():
    path = write_temp_plist(SAMPLE_PLIST)
    result = md.parse_library(path)
    assert "coldplay" not in result

def test_parse_library_handles_missing_artist():
    path = write_temp_plist(SAMPLE_PLIST)
    result = md.parse_library(path)
    assert isinstance(result, dict)
    assert "tom waits" in result
    assert "radiohead" in result

def test_parse_library_mixed_case_deduplication():
    data = {"Tracks": {
        "1": {"Artist": "Tom Waits", "Loved": True},
        "2": {"Artist": "tom waits", "Loved": True},
    }}
    path = write_temp_plist(data)
    result = md.parse_library(path)
    assert list(result.keys()).count("tom waits") == 1

def test_parse_library_empty_tracks():
    path = write_temp_plist({"Tracks": {}})
    result = md.parse_library(path)
    assert result == {}

def test_parse_library_counts_loved_tracks():
    """Artist with 3 loved tracks has count 3."""
    data = {"Tracks": {
        "1": {"Artist": "Tom Waits", "Loved": True},
        "2": {"Artist": "Tom Waits", "Loved": True},
        "3": {"Artist": "Tom Waits", "Loved": True},
    }}
    path = write_temp_plist(data)
    result = md.parse_library(path)
    assert result["tom waits"] == 3

def test_parse_library_counts_mixed_loved_favorited():
    """Loved and Favorited both count toward the total."""
    data = {"Tracks": {
        "1": {"Artist": "Radiohead", "Loved": True},
        "2": {"Artist": "Radiohead", "Favorited": True},
    }}
    path = write_temp_plist(data)
    result = md.parse_library(path)
    assert result["radiohead"] == 2

from unittest.mock import patch, MagicMock

SAMPLE_MUSICMAP_HTML = """
<html><body>
<a href="/nick+cave+%26+the+bad+seeds">Nick Cave &amp; The Bad Seeds</a>
<a href="/leonard+cohen">Leonard Cohen</a>
<a href="/pj+harvey">PJ Harvey</a>
<a href="/">Home</a>
<a href="/about">About</a>
<a href="/gnod">Gnod</a>
</body></html>
"""

def test_scrape_requests_returns_artists():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = SAMPLE_MUSICMAP_HTML
    with patch("requests.get", return_value=mock_resp):
        result = md.scrape_musicmap_requests("tom waits")
    assert isinstance(result, dict)
    assert "nick cave & the bad seeds" in result
    assert "leonard cohen" in result
    assert "pj harvey" in result

def test_scrape_requests_proximity_range():
    """All proximity scores are between 0 and 1 inclusive."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = SAMPLE_MUSICMAP_HTML
    with patch("requests.get", return_value=mock_resp):
        result = md.scrape_musicmap_requests("tom waits")
    for score in result.values():
        assert 0.0 <= score <= 1.0

def test_scrape_requests_first_link_highest_proximity():
    """First link in DOM order has the highest proximity score."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = SAMPLE_MUSICMAP_HTML
    with patch("requests.get", return_value=mock_resp):
        result = md.scrape_musicmap_requests("tom waits")
    scores = list(result.values())
    assert scores[0] == max(scores)

def test_scrape_requests_excludes_nav_links():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = SAMPLE_MUSICMAP_HTML
    with patch("requests.get", return_value=mock_resp):
        result = md.scrape_musicmap_requests("tom waits")
    assert "home" not in result
    assert "about" not in result

def test_scrape_requests_returns_empty_on_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = ""
    with patch("requests.get", return_value=mock_resp):
        result = md.scrape_musicmap_requests("unknown artist xyz")
    assert result == {}

import json

def test_load_cache_returns_empty_dict_if_missing():
    result = md.load_cache("/tmp/nonexistent_cache_xyz_abc_123.json")
    assert result == {}

def test_load_cache_reads_existing_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"tom waits": ["nick cave", "leonard cohen"]}, f)
        path = f.name
    result = md.load_cache(path)
    assert result["tom waits"] == ["nick cave", "leonard cohen"]

def test_save_cache_writes_and_reloads():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    cache = {"radiohead": ["portishead", "bjork"]}
    md.save_cache(cache, path)
    reloaded = md.load_cache(path)
    assert reloaded == cache

def test_stale_cache_entry_detected():
    """Flat-list cache entries are identified as stale."""
    cache = {
        "tom waits":  ["nick cave", "leonard cohen"],    # stale (list)
        "radiohead":  {"portishead": 0.9, "bjork": 0.5}, # fresh (dict)
    }
    stale = md.stale_cache_keys(cache)
    assert stale == ["tom waits"]

def test_no_stale_entries():
    cache = {"tom waits": {"nick cave": 0.9}}
    assert md.stale_cache_keys(cache) == []

def test_empty_cache_no_stale():
    assert md.stale_cache_keys({}) == []

import math

def test_score_artists_basic():
    """Candidate appearing in more library artists scores higher."""
    cache = {
        "tom waits":  {"nick cave": 0.8, "leonard cohen": 0.5},
        "radiohead":  {"nick cave": 0.9, "portishead": 0.6},
    }
    library = {"tom waits": 1, "radiohead": 1}
    ranked = md.score_artists(cache, library)
    scores = {name: s for s, name in ranked}
    assert scores["nick cave"] > scores["leonard cohen"]
    assert scores["nick cave"] > scores["portishead"]

def test_score_artists_engagement_weight():
    """Higher loved_count raises the score (log scale)."""
    cache = {
        "a": {"x": 1.0},
        "b": {"x": 1.0},
    }
    library_low  = {"a": 1, "b": 1}
    library_high = {"a": 10, "b": 10}
    ranked_low  = md.score_artists(cache, library_low)
    ranked_high = md.score_artists(cache, library_high)
    assert ranked_high[0][0] > ranked_low[0][0]

def test_score_artists_excludes_library_artists():
    cache = {"tom waits": {"radiohead": 0.9, "nick cave": 0.8}}
    library = {"tom waits": 2, "radiohead": 1}
    ranked = md.score_artists(cache, library)
    names = [name for _, name in ranked]
    assert "radiohead" not in names
    assert "nick cave" in names

def test_score_artists_sorted_descending():
    cache = {
        "a": {"x": 1.0, "y": 0.5},
        "b": {"x": 0.8, "z": 0.3},
    }
    library = {"a": 3, "b": 1}
    ranked = md.score_artists(cache, library)
    scores = [s for s, _ in ranked]
    assert scores == sorted(scores, reverse=True)

def test_score_artists_formula():
    """Verify exact formula: score = log(loved+1) * proximity."""
    cache = {"a": {"x": 0.5}}
    library = {"a": 3}
    ranked = md.score_artists(cache, library)
    expected = math.log(3 + 1) * 0.5
    assert abs(ranked[0][0] - expected) < 1e-9

def test_score_artists_skips_stale_entries():
    """Flat-list cache entries (stale) are silently skipped."""
    cache = {
        "a": ["x", "y"],         # stale list — skip
        "b": {"x": 0.9},         # fresh dict — use
    }
    library = {"a": 1, "b": 1}
    ranked = md.score_artists(cache, library)
    names = [name for _, name in ranked]
    assert "x" in names
    # score for x should only come from "b" (the fresh entry)
    scores = {name: s for s, name in ranked}
    expected = math.log(1 + 1) * 0.9
    assert abs(scores["x"] - expected) < 1e-9

def test_fetch_filter_data_returns_listeners_and_debut():
    """Returns dict with listeners (int) and debut_year (int)."""
    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = {
        "results": {"artistmatches": {"artist": [
            {"name": "Radiohead", "listeners": "5800000"}
        ]}}
    }
    lastfm_resp = MagicMock()
    lastfm_resp.status_code = 200
    lastfm_resp.json.return_value = {
        "artist": {
            "stats": {"listeners": "5800000"},
            "mbid": "a74b1b7f-71a5-4011-9441-d0b5e4122711",
        }
    }
    mb_resp = MagicMock()
    mb_resp.status_code = 200
    mb_resp.json.return_value = {"life-span": {"begin": "1985-01-01"}}

    with patch("requests.get", side_effect=[search_resp, lastfm_resp, mb_resp]):
        result = md.fetch_filter_data("radiohead", "fake_key")

    assert result["listeners"] == 5_800_000
    assert result["debut_year"] == 1985

def test_fetch_filter_data_missing_mbid():
    """No mbid → debut_year is None, listeners still returned."""
    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = {
        "results": {"artistmatches": {"artist": [
            {"name": "Obscure Band", "listeners": "12000"}
        ]}}
    }
    lastfm_resp = MagicMock()
    lastfm_resp.status_code = 200
    lastfm_resp.json.return_value = {
        "artist": {"stats": {"listeners": "12000"}, "mbid": ""}
    }
    with patch("requests.get", side_effect=[search_resp, lastfm_resp]):
        result = md.fetch_filter_data("obscure band", "fake_key")
    assert result["listeners"] == 12_000
    assert result["debut_year"] is None

def test_fetch_filter_data_lastfm_failure():
    """getInfo non-200 after successful search → returns empty dict."""
    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = {
        "results": {"artistmatches": {"artist": [{"name": "Radiohead"}]}}
    }
    getinfo_resp = MagicMock()
    getinfo_resp.status_code = 500
    with patch("requests.get", side_effect=[search_resp, getinfo_resp]):
        result = md.fetch_filter_data("radiohead", "fake_key")
    assert result == {}

def test_fetch_filter_data_network_error():
    """Network exception → returns empty dict."""
    with patch("requests.get", side_effect=Exception("timeout")):
        result = md.fetch_filter_data("radiohead", "fake_key")
    assert result == {}

def test_fetch_filter_data_year_only_begin():
    """MusicBrainz begin date with year only (no month/day) is parsed correctly."""
    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = {
        "results": {"artistmatches": {"artist": [{"name": "Old Artist"}]}}
    }
    lastfm_resp = MagicMock()
    lastfm_resp.status_code = 200
    lastfm_resp.json.return_value = {
        "artist": {"stats": {"listeners": "1000000"}, "mbid": "some-mbid"}
    }
    mb_resp = MagicMock()
    mb_resp.status_code = 200
    mb_resp.json.return_value = {"life-span": {"begin": "1975"}}
    with patch("requests.get", side_effect=[search_resp, lastfm_resp, mb_resp]):
        result = md.fetch_filter_data("old artist", "fake_key")
    assert result["debut_year"] == 1975


def test_fetch_filter_data_uses_search_for_canonical_name():
    """artist.search top result's name is used in the getInfo call."""
    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = {
        "results": {"artistmatches": {"artist": [
            {"name": "Eagles", "listeners": "5200000"}
        ]}}
    }
    getinfo_resp = MagicMock()
    getinfo_resp.status_code = 200
    getinfo_resp.json.return_value = {
        "artist": {
            "stats": {"listeners": "5200000"},
            "mbid": "f027b01c-1234-5678-abcd-ef0123456789",
        }
    }
    mb_resp = MagicMock()
    mb_resp.status_code = 200
    mb_resp.json.return_value = {"life-span": {"begin": "1971"}}

    calls = []
    def fake_get(url, **kwargs):
        params = kwargs.get("params", {})
        calls.append({
            "method": params.get("method") or "musicbrainz",
            "artist": params.get("artist"),
        })
        return [search_resp, getinfo_resp, mb_resp][len(calls) - 1]

    with patch("requests.get", side_effect=fake_get):
        result = md.fetch_filter_data("the eagles", "fake_key")

    assert calls[0]["method"] == "artist.search"
    assert calls[1]["method"] == "artist.getInfo"
    assert calls[1]["artist"] == "Eagles"   # canonical name, not raw "the eagles"
    assert result["listeners"] == 5_200_000
    assert result["debut_year"] == 1971


def test_fetch_filter_data_falls_back_when_search_empty():
    """If artist.search returns no matches, raw name is used for getInfo."""
    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = {
        "results": {"artistmatches": {"artist": []}}
    }
    getinfo_resp = MagicMock()
    getinfo_resp.status_code = 200
    getinfo_resp.json.return_value = {
        "artist": {"stats": {"listeners": "12000"}, "mbid": ""}
    }

    with patch("requests.get", side_effect=[search_resp, getinfo_resp]):
        result = md.fetch_filter_data("obscure band", "fake_key")

    assert result["listeners"] == 12_000


def test_fetch_filter_data_falls_back_when_search_fails():
    """If artist.search returns non-200, raw name is used for getInfo."""
    search_resp = MagicMock()
    search_resp.status_code = 500

    getinfo_resp = MagicMock()
    getinfo_resp.status_code = 200
    getinfo_resp.json.return_value = {
        "artist": {"stats": {"listeners": "8000"}, "mbid": ""}
    }

    with patch("requests.get", side_effect=[search_resp, getinfo_resp]):
        result = md.fetch_filter_data("some artist", "fake_key")

    assert result["listeners"] == 8_000


def test_fetch_filter_data_both_calls_fail():
    """search non-200 AND getInfo non-200 → returns empty dict."""
    search_resp = MagicMock()
    search_resp.status_code = 500

    getinfo_resp = MagicMock()
    getinfo_resp.status_code = 500

    with patch("requests.get", side_effect=[search_resp, getinfo_resp]):
        result = md.fetch_filter_data("some artist", "fake_key")

    assert result == {}

def test_filter_candidates_removes_popular_classic():
    """Artist with >2M listeners and debut <= 2006 is excluded."""
    scored = [(10.0, "radiohead"), (5.0, "new artist")]
    filter_cache = {
        "radiohead":   {"listeners": 5_800_000, "debut_year": 1985},
        "new artist":  {"listeners": 50_000,    "debut_year": 2015},
    }
    result = md.filter_candidates(scored, filter_cache)
    names = [name for _, name in result]
    assert "radiohead" not in names
    assert "new artist" in names

def test_filter_candidates_keeps_popular_recent():
    """Popular but post-CLASSIC_YEAR artist passes through."""
    scored = [(8.0, "billie eilish")]
    filter_cache = {"billie eilish": {"listeners": 10_000_000, "debut_year": 2016}}
    result = md.filter_candidates(scored, filter_cache)
    names = [name for _, name in result]
    assert "billie eilish" in names

def test_filter_candidates_keeps_classic_obscure():
    """Old artist with low listeners passes through."""
    scored = [(3.0, "nick cave")]
    filter_cache = {"nick cave": {"listeners": 40_000, "debut_year": 1980}}
    result = md.filter_candidates(scored, filter_cache)
    names = [name for _, name in result]
    assert "nick cave" in names

def test_filter_candidates_passes_through_empty_data():
    """Artist with empty filter data ({}) passes through."""
    scored = [(5.0, "unknown artist")]
    filter_cache = {"unknown artist": {}}
    result = md.filter_candidates(scored, filter_cache)
    names = [name for _, name in result]
    assert "unknown artist" in names

def test_filter_candidates_passes_through_missing_debut():
    """Artist with listeners but no debut_year passes through."""
    scored = [(5.0, "some artist")]
    filter_cache = {"some artist": {"listeners": 5_000_000, "debut_year": None}}
    result = md.filter_candidates(scored, filter_cache)
    names = [name for _, name in result]
    assert "some artist" in names

def test_filter_candidates_preserves_order():
    """Output preserves the input score ordering."""
    scored = [(10.0, "a"), (7.0, "b"), (3.0, "c")]
    filter_cache = {"a": {}, "b": {}, "c": {}}
    result = md.filter_candidates(scored, filter_cache)
    assert result == [(10.0, "a"), (7.0, "b"), (3.0, "c")]


# ── load_dotenv ────────────────────────────────────────────

def test_load_dotenv_sets_key(tmp_path, monkeypatch):
    """load_dotenv() reads a KEY=value pair from .env into os.environ."""
    env_file = tmp_path / ".env"
    env_file.write_text("LASTFM_API_KEY=testkey123\n")
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    md.load_dotenv(env_file)
    assert os.environ.get("LASTFM_API_KEY") == "testkey123"

def test_load_dotenv_ignores_comments(tmp_path, monkeypatch):
    """Lines starting with # are ignored."""
    env_file = tmp_path / ".env"
    env_file.write_text("# this is a comment\nLASTFM_API_KEY=fromfile\n")
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    md.load_dotenv(env_file)
    assert os.environ.get("LASTFM_API_KEY") == "fromfile"

def test_load_dotenv_ignores_blank_lines(tmp_path, monkeypatch):
    """Blank lines are skipped without error."""
    env_file = tmp_path / ".env"
    env_file.write_text("\n\nLASTFM_API_KEY=fromfile\n\n")
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    md.load_dotenv(env_file)
    assert os.environ.get("LASTFM_API_KEY") == "fromfile"

def test_load_dotenv_does_not_override_existing(tmp_path, monkeypatch):
    """Keys already in os.environ are not overwritten."""
    env_file = tmp_path / ".env"
    env_file.write_text("LASTFM_API_KEY=fromfile\n")
    monkeypatch.setenv("LASTFM_API_KEY", "fromenv")
    md.load_dotenv(env_file)
    assert os.environ.get("LASTFM_API_KEY") == "fromenv"

def test_load_dotenv_missing_file_does_not_raise(tmp_path):
    """Missing .env prints a note but does not raise."""
    md.load_dotenv(tmp_path / "nonexistent.env")  # must not raise

def test_load_dotenv_strips_quoted_values(tmp_path, monkeypatch):
    """Surrounding quotes are stripped from values."""
    env_file = tmp_path / ".env"
    env_file.write_text('LASTFM_API_KEY="mykey"\n')
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    md.load_dotenv(env_file)
    assert os.environ.get("LASTFM_API_KEY") == "mykey"


# ── _build_paths ───────────────────────────────────────────

def test_build_paths_default_filenames(monkeypatch):
    """Default paths use the expected filenames."""
    monkeypatch.delenv("CACHE_DIR",  raising=False)
    monkeypatch.delenv("OUTPUT_DIR", raising=False)
    paths = md._build_paths()
    assert paths["cache"].name        == "music_map_cache.json"
    assert paths["filter_cache"].name == "filter_cache.json"
    assert paths["output"].name       == "music_discovery_results.txt"

def test_build_paths_respects_cache_dir(tmp_path, monkeypatch):
    """CACHE_DIR env var controls where cache files go."""
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("OUTPUT_DIR", raising=False)
    paths = md._build_paths()
    assert paths["cache"].parent        == tmp_path
    assert paths["filter_cache"].parent == tmp_path

def test_build_paths_respects_output_dir(tmp_path, monkeypatch):
    """OUTPUT_DIR env var controls where the results file goes."""
    monkeypatch.delenv("CACHE_DIR", raising=False)
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    paths = md._build_paths()
    assert paths["output"].parent == tmp_path

def test_build_paths_creates_directories(tmp_path, monkeypatch):
    """Missing directories are created automatically."""
    new_dir = tmp_path / "nested" / "cache"
    monkeypatch.setenv("CACHE_DIR",  str(new_dir))
    monkeypatch.setenv("OUTPUT_DIR", str(new_dir))
    md._build_paths()
    assert new_dir.exists()


# ── _run_applescript ────────────────────────────────────────

def test_run_applescript_has_timeout(monkeypatch):
    """_run_applescript passes a timeout to subprocess.run."""
    captured = {}
    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        result = MagicMock()
        result.stdout = ""
        result.returncode = 0
        return result
    monkeypatch.setattr(subprocess, "run", fake_run)
    md._run_applescript('return "hi"')
    assert "timeout" in captured
    assert captured["timeout"] >= 30


# ── XML fallback ────────────────────────────────────────────

def test_fallback_writes_xml_when_build_fails(tmp_path):
    """When build_playlist returns (False, tracks), the fallback writes XML."""
    tracks = [
        {"name": "Creep", "artist": "Radiohead"},
        {"name": "Karma Police", "artist": "Radiohead"},
    ]
    xml_path = tmp_path / "Music Discovery.xml"
    success = False
    if not success and tracks:
        md.write_playlist_xml(tracks, xml_path)
    assert xml_path.exists()
    with open(xml_path, "rb") as f:
        plist = plistlib.load(f)
    assert len(plist["Tracks"]) == 2

def test_fallback_skips_xml_when_no_tracks(tmp_path):
    """No XML written if build_playlist fails with empty track list."""
    xml_path = tmp_path / "Music Discovery.xml"
    success = False
    tracks = []
    if not success and tracks:
        md.write_playlist_xml(tracks, xml_path)
    assert not xml_path.exists()


# ── fetch_top_tracks ──────────────────────────────────────

def test_fetch_top_tracks_returns_track_list():
    """Returns list of {name, artist} dicts from Last.fm getTopTracks."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "toptracks": {"track": [
            {"name": "Creep", "artist": {"name": "Radiohead"}},
            {"name": "Karma Police", "artist": {"name": "Radiohead"}},
        ]}
    }
    with patch("requests.get", return_value=resp):
        result = md.fetch_top_tracks("radiohead", "fake_key")
    assert result == [
        {"name": "Creep", "artist": "Radiohead"},
        {"name": "Karma Police", "artist": "Radiohead"},
    ]

def test_fetch_top_tracks_api_error_returns_empty():
    """Non-200 response returns empty list."""
    resp = MagicMock()
    resp.status_code = 500
    with patch("requests.get", return_value=resp):
        result = md.fetch_top_tracks("radiohead", "fake_key")
    assert result == []

def test_fetch_top_tracks_skips_nameless():
    """Tracks with empty name are skipped."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "toptracks": {"track": [
            {"name": "Creep", "artist": {"name": "Radiohead"}},
            {"name": "", "artist": {"name": "Radiohead"}},
        ]}
    }
    with patch("requests.get", return_value=resp):
        result = md.fetch_top_tracks("radiohead", "fake_key")
    assert len(result) == 1
    assert result[0]["name"] == "Creep"

def test_fetch_top_tracks_network_error_returns_empty():
    """Network exception returns empty list."""
    with patch("requests.get", side_effect=Exception("timeout")):
        result = md.fetch_top_tracks("radiohead", "fake_key")
    assert result == []


# ── search_itunes ─────────────────────────────────────────

def test_search_itunes_returns_track_id(monkeypatch):
    """Returns store track ID string on success."""
    mock_resp = type("R", (), {
        "status_code": 200,
        "json": lambda self: {"resultCount": 1, "results": [{"trackId": 12345}]},
    })()
    monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)
    assert md.search_itunes("Radiohead", "Creep") == "12345"

def test_search_itunes_returns_none_on_no_results(monkeypatch):
    """Returns None when no tracks found."""
    mock_resp = type("R", (), {
        "status_code": 200,
        "json": lambda self: {"resultCount": 0, "results": []},
    })()
    monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)
    assert md.search_itunes("Nobody", "Fake") is None

def test_search_itunes_returns_none_on_error(monkeypatch):
    """Returns None on network error."""
    monkeypatch.setattr("requests.get", lambda *a, **kw: (_ for _ in ()).throw(Exception("timeout")))
    assert md.search_itunes("Radiohead", "Creep") is None


# ── setup_playlist ────────────────────────────────────────

def test_setup_playlist_returns_true_on_success(monkeypatch):
    """Returns True when osascript succeeds."""
    responses = iter([("-1", 0), ("", 0)])
    monkeypatch.setattr(md, "_run_applescript", lambda script: next(responses))
    assert md.setup_playlist() is True

def test_setup_playlist_returns_false_on_failure(monkeypatch):
    """Returns False when osascript fails."""
    monkeypatch.setattr(md, "_run_applescript", lambda script: ("error", 1))
    assert md.setup_playlist() is False

def test_setup_playlist_script_references_playlist_name(monkeypatch):
    """The AppleScript contains the playlist name."""
    captured = []
    def fake_run(script):
        captured.append(script)
        return ("", 0)
    monkeypatch.setattr(md, "_run_applescript", fake_run)
    md.setup_playlist()
    assert "Music Discovery" in captured[0]


# ── add_track_to_playlist ─────────────────────────────────

def test_add_track_to_playlist_returns_true_on_ok(monkeypatch):
    """Returns True when full flow succeeds."""
    monkeypatch.setattr(md, "search_itunes", lambda a, t: "12345")
    monkeypatch.setattr(md, "_play_store_track", lambda sid: True)
    responses = iter([
        ("not_found", 0),          # dedup check
        ("Old|||Track", 0),        # snapshot current track
        ("Creep|||Radiohead", 0),  # poll — different from snapshot, breaks loop
        ("ok", 0),                 # add to library + playlist
    ])
    monkeypatch.setattr(md, "_run_applescript", lambda script: next(responses))
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert md.add_track_to_playlist("Radiohead", "Creep") is True

def test_add_track_to_playlist_returns_false_when_not_on_apple_music(monkeypatch):
    """Returns False when iTunes Search API finds nothing."""
    monkeypatch.setattr(md, "search_itunes", lambda a, t: None)
    assert md.add_track_to_playlist("Nobody", "Fake Song") is False

def test_add_track_to_playlist_raises_on_osascript_failure(monkeypatch):
    """Raises RuntimeError when osascript returns non-zero."""
    monkeypatch.setattr(md, "search_itunes", lambda a, t: "12345")
    monkeypatch.setattr(md, "_play_store_track", lambda sid: True)
    responses = iter([
        ("not_found", 0),          # dedup check
        ("Old|||Track", 0),        # snapshot
        ("Creep|||Radiohead", 0),  # poll — breaks loop
        ("", 1),                   # add-to-playlist fails
    ])
    monkeypatch.setattr(md, "_run_applescript", lambda script: next(responses))
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        md.add_track_to_playlist("Radiohead", "Creep")


# ── write_playlist_xml ────────────────────────────────────

def test_write_playlist_xml_creates_valid_plist(tmp_path):
    """Writes an XML plist with Tracks and Playlists keys."""
    output = tmp_path / "test.xml"
    tracks = [
        {"name": "Creep", "artist": "Radiohead"},
        {"name": "Red Right Hand", "artist": "Nick Cave"},
    ]
    md.write_playlist_xml(tracks, output)
    assert output.exists()
    with open(output, "rb") as f:
        plist = plistlib.load(f)
    assert "Tracks" in plist
    assert "Playlists" in plist
    assert len(plist["Tracks"]) == 2
    assert len(plist["Playlists"][0]["Playlist Items"]) == 2

def test_write_playlist_xml_empty_tracks(tmp_path):
    """Empty track list produces valid plist with no tracks."""
    output = tmp_path / "test.xml"
    md.write_playlist_xml([], output)
    with open(output, "rb") as f:
        plist = plistlib.load(f)
    assert plist["Tracks"] == {}
    assert plist["Playlists"][0]["Playlist Items"] == []

def test_write_playlist_xml_track_metadata(tmp_path):
    """Track entries contain Name and Artist."""
    output = tmp_path / "test.xml"
    md.write_playlist_xml([{"name": "Creep", "artist": "Radiohead"}], output)
    with open(output, "rb") as f:
        plist = plistlib.load(f)
    track = list(plist["Tracks"].values())[0]
    assert track["Name"] == "Creep"
    assert track["Artist"] == "Radiohead"


# ── build_playlist ────────────────────────────────────────

def test_build_playlist_calls_setup_and_adds_tracks(monkeypatch, tmp_path):
    """build_playlist calls setup_playlist then adds each track."""
    monkeypatch.setattr(md, "setup_playlist", lambda: True)
    monkeypatch.setattr(md, "_stop_playback", lambda: None)
    add_calls = []
    monkeypatch.setattr(md, "add_track_to_playlist",
                        lambda artist, track: add_calls.append((artist, track)) or True)
    monkeypatch.setattr(md, "load_cache", lambda p: {
        "radiohead": [{"name": "Creep", "artist": "Radiohead"}],
    })
    monkeypatch.setattr(md, "save_cache", lambda c, p: None)
    monkeypatch.setattr(md, "fetch_top_tracks", lambda a, k: [])
    monkeypatch.setattr("time.sleep", lambda s: None)
    ranked = [(10.0, "radiohead")]
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    paths = md._build_paths()
    success, tracks = md.build_playlist(ranked, "fake_key", paths)
    assert success is True
    assert ("Radiohead", "Creep") in add_calls

def test_build_playlist_returns_false_on_setup_failure(monkeypatch, tmp_path):
    """Returns (False, tracks) when setup_playlist fails."""
    monkeypatch.setattr(md, "setup_playlist", lambda: False)
    monkeypatch.setattr(md, "load_cache", lambda p: {})
    monkeypatch.setattr(md, "save_cache", lambda c, p: None)
    monkeypatch.setattr(md, "fetch_top_tracks", lambda a, k: [])
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    paths = md._build_paths()
    ranked = [(10.0, "radiohead")]
    success, _ = md.build_playlist(ranked, "fake_key", paths)
    assert success is False

def test_build_playlist_empty_ranked(monkeypatch, tmp_path):
    """Empty ranked list skips playlist generation."""
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    paths = md._build_paths()
    success, tracks = md.build_playlist([], "fake_key", paths)
    assert success is True
    assert tracks == []

def test_get_machine_seed_returns_32_bytes():
    seed = md._get_machine_seed()
    assert isinstance(seed, bytes)
    assert len(seed) == 32


def test_encrypt_decrypt_round_trip():
    key = "888714dde5ecaef3354ef133d9320559"
    encrypted = md.encrypt_key(key)
    decrypted = md.decrypt_key(encrypted)
    assert decrypted == key

def test_encrypted_output_not_plaintext():
    key = "888714dde5ecaef3354ef133d9320559"
    encrypted = md.encrypt_key(key)
    assert key not in encrypted


def test_build_playlist_handles_runtime_error_gracefully(monkeypatch, tmp_path):
    """RuntimeError in add_track_to_playlist is caught; track is skipped."""
    monkeypatch.setattr(md, "setup_playlist", lambda: True)
    monkeypatch.setattr(md, "_stop_playback", lambda: None)
    def raise_error(artist, track):
        raise RuntimeError("osascript failed")
    monkeypatch.setattr(md, "add_track_to_playlist", raise_error)
    monkeypatch.setattr(md, "load_cache", lambda p: {
        "radiohead": [{"name": "Creep", "artist": "Radiohead"}],
    })
    monkeypatch.setattr(md, "save_cache", lambda c, p: None)
    monkeypatch.setattr(md, "fetch_top_tracks", lambda a, k: [])
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    paths = md._build_paths()
    ranked = [(10.0, "radiohead")]
    success, tracks = md.build_playlist(ranked, "fake_key", paths)
    assert success is True
    assert len(tracks) > 0


import hashlib


def test_validate_api_key_accepts_valid():
    assert md._validate_api_key("888714dde5ecaef3354ef133d9320559") is True

def test_validate_api_key_rejects_short():
    assert md._validate_api_key("888714dde5ecaef3") is False

def test_validate_api_key_rejects_non_hex():
    assert md._validate_api_key("zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz") is False

def test_validate_api_key_rejects_empty():
    assert md._validate_api_key("") is False

def test_decrypt_wrong_seed_fails_validation():
    """Decrypting with wrong bytes produces output that fails validation."""
    key = "888714dde5ecaef3354ef133d9320559"
    encrypted = md.encrypt_key(key)
    # XOR with a different seed to simulate hardware change
    wrong_seed = hashlib.sha256(b"wrong").digest()
    cipher_bytes = bytes.fromhex(encrypted)
    bad_result = bytes(a ^ b for a, b in zip(cipher_bytes, wrong_seed))
    try:
        text = bad_result.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
    assert not md._validate_api_key(text)

def test_get_machine_seed_darwin_ioreg_fails_returns_none():
    """On macOS, if ioreg fails, returns None."""
    with patch("music_discovery.platform.system", return_value="Darwin"), \
         patch("music_discovery.subprocess.run", side_effect=Exception("no ioreg")):
        assert md._get_machine_seed() is None

def test_get_machine_seed_windows_registry_fails_returns_none():
    """On Windows, if registry read fails, returns None."""
    mock_winreg = MagicMock()
    mock_winreg.OpenKey = MagicMock(side_effect=Exception("no key"))
    mock_winreg.HKEY_LOCAL_MACHINE = 0x80000002
    with patch("music_discovery.platform.system", return_value="Windows"), \
         patch.dict("sys.modules", {"winreg": mock_winreg}):
        assert md._get_machine_seed() is None

def test_get_machine_seed_linux_no_machine_id_returns_none():
    """On Linux, if /etc/machine-id is missing, returns None."""
    with patch("music_discovery.platform.system", return_value="Linux"), \
         patch("music_discovery.pathlib.Path.read_text", side_effect=FileNotFoundError):
        assert md._get_machine_seed() is None


def test_write_key_to_env_creates_new_file(tmp_path):
    env_path = tmp_path / ".env"
    md._write_key_to_env("ENC:abc123", env_path)
    assert env_path.read_text() == "LASTFM_API_KEY=ENC:abc123\n"

def test_write_key_to_env_appends_to_existing(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("CACHE_DIR=~/my_cache\n")
    md._write_key_to_env("ENC:abc123", env_path)
    content = env_path.read_text()
    assert "CACHE_DIR=~/my_cache" in content
    assert "LASTFM_API_KEY=ENC:abc123" in content

def test_write_key_to_env_replaces_existing_key(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("CACHE_DIR=~/my_cache\nLASTFM_API_KEY=old_value\nOUTPUT_DIR=~/out\n")
    md._write_key_to_env("ENC:new_value", env_path)
    content = env_path.read_text()
    assert "LASTFM_API_KEY=ENC:new_value" in content
    assert "old_value" not in content
    assert "CACHE_DIR=~/my_cache" in content
    assert "OUTPUT_DIR=~/out" in content


def test_prompt_for_api_key_success(tmp_path):
    env_path = tmp_path / ".env"
    with patch("music_discovery.getpass.getpass", return_value="888714dde5ecaef3354ef133d9320559"):
        result = md.prompt_for_api_key(env_path=env_path)
    assert result == "888714dde5ecaef3354ef133d9320559"
    content = env_path.read_text()
    # Should be encrypted (ENC: prefix) or plain depending on machine seed
    assert "LASTFM_API_KEY=" in content

def test_prompt_for_api_key_retries_on_invalid(tmp_path):
    env_path = tmp_path / ".env"
    with patch("music_discovery.getpass.getpass", side_effect=["bad", "also_bad", "888714dde5ecaef3354ef133d9320559"]):
        result = md.prompt_for_api_key(env_path=env_path)
    assert result == "888714dde5ecaef3354ef133d9320559"

def test_prompt_for_api_key_exits_after_3_failures(tmp_path):
    env_path = tmp_path / ".env"
    with patch("music_discovery.getpass.getpass", side_effect=["bad", "bad", "bad"]):
        result = md.prompt_for_api_key(env_path=env_path)
    assert result is None


def test_load_dotenv_decrypts_enc_prefix(tmp_path, monkeypatch):
    key = "888714dde5ecaef3354ef133d9320559"
    encrypted = md.encrypt_key(key)
    env_path = tmp_path / ".env"
    env_path.write_text(f"LASTFM_API_KEY=ENC:{encrypted}\n")
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    md.load_dotenv(env_path)
    assert os.environ.get("LASTFM_API_KEY") == key
    # Clean up
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)

def test_load_dotenv_plain_text_backward_compat(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("LASTFM_API_KEY=888714dde5ecaef3354ef133d9320559\n")
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    md.load_dotenv(env_path)
    assert os.environ.get("LASTFM_API_KEY") == "888714dde5ecaef3354ef133d9320559"
    # Clean up
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)


# ── _resolve_library_path ─────────────────────────────────

def test_resolve_library_path_cli_override(tmp_path):
    """CLI --library flag takes precedence over auto-detect."""
    fake_xml = tmp_path / "MyLibrary.xml"
    fake_xml.write_bytes(b"<plist></plist>")
    result = md._resolve_library_path(str(fake_xml))
    assert result == fake_xml


def test_resolve_library_path_cli_override_missing():
    """CLI --library with nonexistent file returns None."""
    result = md._resolve_library_path("/nonexistent/library.xml")
    assert result is None


def test_resolve_library_path_auto_detect(monkeypatch):
    """Auto-detect returns a Path based on platform."""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    result = md._resolve_library_path(None)
    # Should return the macOS default path (may not exist, that's OK)
    assert "Music" in str(result) or result is None


def test_prompt_for_api_key_skip(monkeypatch):
    """Pressing Enter (empty input) returns None immediately."""
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "")
    result = md.prompt_for_api_key(env_path="/tmp/fake.env")
    assert result is None


def test_resolve_library_path_windows(monkeypatch):
    """Auto-detect on Windows returns iTunes path."""
    monkeypatch.setattr("platform.system", lambda: "Windows")
    result = md._resolve_library_path(None)
    assert result is None or "iTunes" in str(result)


# ── load_user_blocklist ───────────────────────────────────

def test_load_user_blocklist_reads_names(tmp_path):
    """Reads one name per line, lowercased, ignoring blanks and comments."""
    f = tmp_path / "blocklist.txt"
    f.write_text("Hall and Oates\n# a comment\n\nBlondie\n")
    result = md.load_user_blocklist(f)
    assert result == {"hall and oates", "blondie"}


def test_load_user_blocklist_missing_file(tmp_path):
    """Returns empty set when file does not exist."""
    result = md.load_user_blocklist(tmp_path / "nope.txt")
    assert result == set()


def test_auto_export_library_returns_path_on_success(tmp_path):
    """On macOS, auto_export_library should call osascript and return the export path."""
    export_path = tmp_path / "Library.xml"
    export_path.write_bytes(plistlib.dumps({"Tracks": {}}))
    mock_result = MagicMock(returncode=0, stderr="")
    with patch('subprocess.run', return_value=mock_result) as mock_run:
        result = md.auto_export_library(tmp_path)
    assert result == export_path
    mock_run.assert_called_once()
    assert mock_run.call_args[0][0][0] == "osascript"

def test_auto_export_library_returns_none_on_failure(tmp_path):
    """If osascript returns non-zero, return None."""
    mock_result = MagicMock(returncode=1, stderr="error")
    with patch('subprocess.run', return_value=mock_result):
        result = md.auto_export_library(tmp_path)
    assert result is None

def test_auto_export_library_returns_none_on_timeout(tmp_path):
    """If osascript times out, return None."""
    with patch('subprocess.run', side_effect=subprocess.TimeoutExpired("osascript", 120)):
        result = md.auto_export_library(tmp_path)
    assert result is None

def test_auto_export_library_returns_none_when_no_file(tmp_path):
    """If osascript succeeds but no file is produced, return None."""
    mock_result = MagicMock(returncode=0, stderr="")
    with patch('subprocess.run', return_value=mock_result):
        result = md.auto_export_library(tmp_path)
    assert result is None


def test_build_playlist_xml_only_skips_setup(monkeypatch, tmp_path):
    """xml_only=True returns tracks without calling setup_playlist."""
    paths = {
        "top_tracks": tmp_path / "top_tracks.json",
        "playlist_xml": tmp_path / "playlist.xml",
    }
    paths["top_tracks"].write_text("{}")
    ranked = [(5.0, "test artist")]

    # Mock fetch_top_tracks to return a track
    monkeypatch.setattr(md, "fetch_top_tracks", lambda *a, **kw: [{"name": "Song", "artist": "Test Artist"}])
    monkeypatch.setattr(md, "save_cache", lambda *a: None)

    # setup_playlist should NOT be called — if it is, fail
    def fail_setup():
        raise AssertionError("setup_playlist should not be called")
    monkeypatch.setattr(md, "setup_playlist", fail_setup)

    success, tracks = md.build_playlist(ranked, "fake-key", paths, xml_only=True)
    assert success is True
    assert len(tracks) >= 1
