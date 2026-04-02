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
    result, _ = md.parse_library(path)
    assert "tom waits" in result

def test_parse_library_favorited():
    path = write_temp_plist({"Tracks": {"1": {"Artist": "Radiohead", "Favorited": True}}})
    result, _ = md.parse_library(path)
    assert "radiohead" in result

def test_parse_library_deduplicates():
    path = write_temp_plist(SAMPLE_PLIST)
    result, _ = md.parse_library(path)
    assert list(result.keys()).count("tom waits") == 1

def test_parse_library_excludes_unloved():
    path = write_temp_plist(SAMPLE_PLIST)
    result, _ = md.parse_library(path)
    assert "coldplay" not in result

def test_parse_library_handles_missing_artist():
    path = write_temp_plist(SAMPLE_PLIST)
    result, _ = md.parse_library(path)
    assert isinstance(result, dict)
    assert "tom waits" in result
    assert "radiohead" in result

def test_parse_library_mixed_case_deduplication():
    data = {"Tracks": {
        "1": {"Artist": "Tom Waits", "Loved": True},
        "2": {"Artist": "tom waits", "Loved": True},
    }}
    path = write_temp_plist(data)
    result, _ = md.parse_library(path)
    assert list(result.keys()).count("tom waits") == 1

def test_parse_library_empty_tracks():
    path = write_temp_plist({"Tracks": {}})
    result, _ = md.parse_library(path)
    assert result == {}

def test_parse_library_counts_loved_tracks():
    """Artist with 3 loved tracks has count 3."""
    data = {"Tracks": {
        "1": {"Artist": "Tom Waits", "Loved": True},
        "2": {"Artist": "Tom Waits", "Loved": True},
        "3": {"Artist": "Tom Waits", "Loved": True},
    }}
    path = write_temp_plist(data)
    result, _ = md.parse_library(path)
    assert result["tom waits"] == 3

def test_parse_library_counts_mixed_loved_favorited():
    """Loved and Favorited both count toward the total."""
    data = {"Tracks": {
        "1": {"Artist": "Radiohead", "Loved": True},
        "2": {"Artist": "Radiohead", "Favorited": True},
    }}
    path = write_temp_plist(data)
    result, _ = md.parse_library(path)
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
    """Verify exact formula: score = sqrt(log(loved+1)) * proximity."""
    cache = {"a": {"x": 0.5}}
    library = {"a": 3}
    ranked = md.score_artists(cache, library)
    expected = math.log(3 + 1) ** 0.5 * 0.5
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
    expected = math.log(1 + 1) ** 0.5 * 0.9
    assert abs(scores["x"] - expected) < 1e-9

def test_score_artists_negative_scoring():
    """Blocklisted artist neighbors receive a score penalty."""
    cache = {
        "loved1": {"cand_a": 0.8, "cand_b": 0.6},
    }
    library = {"loved1": 5}
    blocklist_cache = {
        "hated1": {"cand_a": 0.9, "cand_c": 0.7},
    }
    user_blocklist = {"hated1"}

    baseline = md.score_artists(cache, library)
    baseline_scores = {name: s for s, name in baseline}

    result = md.score_artists(cache, library, blocklist_cache, user_blocklist)
    result_scores = {name: s for s, name in result}

    assert result_scores["cand_a"] < baseline_scores["cand_a"]
    assert result_scores["cand_b"] == pytest.approx(baseline_scores["cand_b"], abs=1e-9)
    assert result_scores["cand_c"] < 0

def test_score_artists_negative_formula():
    """Verify exact negative scoring formula."""
    cache = {
        "loved1": {"cand_x": 0.5},
    }
    library = {"loved1": 3}
    blocklist_cache = {
        "hated1": {"cand_x": 0.7},
    }
    user_blocklist = {"hated1"}

    result = md.score_artists(cache, library, blocklist_cache, user_blocklist)
    result_scores = {name: s for s, name in result}

    positive = math.log(3 + 1) ** 0.5 * 0.5
    negative = md.NEGATIVE_PENALTY * 0.7
    expected = positive - negative

    assert result_scores["cand_x"] == pytest.approx(expected, abs=1e-9)

def test_score_artists_excludes_blocklisted_artists():
    """Blocklisted artists themselves never appear in scored output."""
    cache = {
        "loved1": {"hated1": 0.9, "cand_a": 0.5},
    }
    library = {"loved1": 2}
    blocklist_cache = {
        "hated1": {"cand_a": 0.3},
    }
    user_blocklist = {"hated1"}

    result = md.score_artists(cache, library, blocklist_cache, user_blocklist)
    names = [name for _, name in result]

    assert "hated1" not in names
    assert "cand_a" in names

def test_score_artists_backward_compatible():
    """Calling without blocklist args produces identical results to old behavior."""
    cache = {
        "loved1": {"cand_a": 0.8, "cand_b": 0.4},
        "loved2": {"cand_a": 0.6},
    }
    library = {"loved1": 5, "loved2": 3}

    result_old_style = md.score_artists(cache, library)
    result_new_style = md.score_artists(cache, library, blocklist_cache=None, user_blocklist=None)

    assert result_old_style == result_new_style

def test_score_artists_negative_skips_stale():
    """Stale flat-list entries in blocklist_cache are silently skipped."""
    cache = {
        "loved1": {"cand_a": 0.8},
    }
    library = {"loved1": 2}
    blocklist_cache = {
        "hated1": ["cand_a", "cand_b"],      # stale list format — skip
        "hated2": {"cand_a": 0.6},            # fresh dict — apply penalty
    }
    user_blocklist = {"hated1", "hated2"}

    result = md.score_artists(cache, library, blocklist_cache, user_blocklist)
    result_scores = {name: s for s, name in result}

    positive = math.log(2 + 1) ** 0.5 * 0.8
    negative = md.NEGATIVE_PENALTY * 0.6
    expected = positive - negative

    assert result_scores["cand_a"] == pytest.approx(expected, abs=1e-9)

def test_negative_penalty_milder_than_positive():
    """Verify that NEGATIVE_PENALTY < smallest possible positive weight."""
    min_positive_weight = math.log(1 + 1) ** 0.5
    assert md.NEGATIVE_PENALTY < min_positive_weight

def test_rejected_artists_excludes_manual_blocklist():
    """rejected_artists = file_blocklist - user_blocklist (taste rejections only)."""
    # Simulate what main() does: file_blocklist from blocklist_cache.json
    # contains both auto-rejected and manual entries
    file_blocklist = {"arch echo", "chon", "reo speedwagon", "blondie"}
    user_blocklist = {"reo speedwagon", "blondie"}
    rejected_artists = file_blocklist - user_blocklist

    assert rejected_artists == {"arch echo", "chon"}
    assert "reo speedwagon" not in rejected_artists
    assert "blondie" not in rejected_artists


def test_negative_scoring_effective_with_rejected_artists():
    """Rejected artists (former candidates) have neighbor overlap with current candidates.
    Manual blocklist artists (classic pop/rock) do not.
    This test demonstrates the rework rationale."""
    # Candidate pool: prog metal / math rock
    cache = {
        "haken": {"leprous": 0.9, "caligulas horse": 0.85, "tesseract": 0.8},
        "animals as leaders": {"plini": 0.88, "chon": 0.82, "polyphia": 0.75},
    }
    library = {"haken": 3, "animals as leaders": 2}

    # Manual blocklist neighbors: classic pop/rock — NO overlap with prog candidates
    manual_bl_cache = {
        "reo speedwagon": {"air supply": 0.78, "loverboy": 0.76, "mr. mister": 0.80},
    }

    # Rejected artist neighbors: former candidates — HIGH overlap
    rejected_bl_cache = {
        "chon": {"polyphia": 0.90, "plini": 0.85, "covet": 0.80},
    }

    user_blocklist = {"reo speedwagon"}

    # With manual blocklist scrape: scores unchanged (no overlap)
    scored_manual = md.score_artists(cache, library, manual_bl_cache, user_blocklist)
    scored_manual_d = {name: s for s, name in scored_manual}

    # With rejected artist scrape: polyphia and plini get penalized
    scored_rejected = md.score_artists(cache, library, rejected_bl_cache, user_blocklist)
    scored_rejected_d = {name: s for s, name in scored_rejected}

    # polyphia appears in both loved and rejected neighborhoods — should be penalized
    assert scored_rejected_d["polyphia"] < scored_manual_d["polyphia"]

    # plini appears in both loved and rejected neighborhoods — should be penalized
    assert scored_rejected_d["plini"] < scored_manual_d["plini"]

    # leprous only in loved neighborhoods — score identical either way
    assert scored_rejected_d["leprous"] == pytest.approx(scored_manual_d["leprous"], abs=1e-9)


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
        "artist": {
            "stats": {"listeners": "12000"},
            "mbid": "",
            "bio": {"content": ""},
            "tags": {"tag": []},
        }
    }
    mb_search_resp = MagicMock()
    mb_search_resp.status_code = 200
    mb_search_resp.json.return_value = {"artists": []}
    with patch("requests.get", side_effect=[search_resp, lastfm_resp, mb_search_resp]):
        with patch("time.sleep"):
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
        "artist": {
            "stats": {"listeners": "12000"},
            "mbid": "",
            "bio": {"content": ""},
            "tags": {"tag": []},
        }
    }
    mb_search_resp = MagicMock()
    mb_search_resp.status_code = 200
    mb_search_resp.json.return_value = {"artists": []}

    with patch("requests.get", side_effect=[search_resp, getinfo_resp, mb_search_resp]):
        with patch("time.sleep"):
            result = md.fetch_filter_data("obscure band", "fake_key")

    assert result["listeners"] == 12_000


def test_fetch_filter_data_falls_back_when_search_fails():
    """If artist.search returns non-200, raw name is used for getInfo."""
    search_resp = MagicMock()
    search_resp.status_code = 500

    getinfo_resp = MagicMock()
    getinfo_resp.status_code = 200
    getinfo_resp.json.return_value = {
        "artist": {
            "stats": {"listeners": "8000"},
            "mbid": "",
            "bio": {"content": ""},
            "tags": {"tag": []},
        }
    }
    mb_search_resp = MagicMock()
    mb_search_resp.status_code = 200
    mb_search_resp.json.return_value = {"artists": []}

    with patch("requests.get", side_effect=[search_resp, getinfo_resp, mb_search_resp]):
        with patch("time.sleep"):
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


def test_fetch_filter_data_extracts_bio_tags_mb_type():
    """Returns bio_length, tag_count, mb_type, mb_has_releases from API responses."""
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
            "bio": {"content": "Radiohead are an English rock band. " * 5},
            "tags": {"tag": [{"name": "rock"}, {"name": "alternative"}]},
        }
    }
    mb_resp = MagicMock()
    mb_resp.status_code = 200
    mb_resp.json.return_value = {
        "life-span": {"begin": "1985-01-01"},
        "type": "Group",
        "releases": [{"title": "OK Computer"}],
        "relations": [],
    }
    with patch("requests.get", side_effect=[search_resp, lastfm_resp, mb_resp]):
        result = md.fetch_filter_data("radiohead", "fake_key")
    assert result["bio_length"] > 50
    assert result["tag_count"] == 2
    assert result["mb_type"] == "Group"
    assert result["mb_has_releases"] is True


def test_fetch_filter_data_no_mbid_falls_back_to_mb_search():
    """When Last.fm returns no MBID, falls back to MusicBrainz name search + MBID detail."""
    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = {
        "results": {"artistmatches": {"artist": [{"name": "Fake Band"}]}}
    }
    lastfm_resp = MagicMock()
    lastfm_resp.status_code = 200
    lastfm_resp.json.return_value = {
        "artist": {
            "stats": {"listeners": "500"},
            "mbid": "",
            "bio": {"content": ""},
            "tags": {"tag": []},
        }
    }
    # MusicBrainz search returns a match (no releases in search response)
    mb_search_resp = MagicMock()
    mb_search_resp.status_code = 200
    mb_search_resp.json.return_value = {
        "artists": [{
            "name": "Fake Band",
            "id": "abc-123",
            "score": 100,
            "type": "Group",
        }]
    }
    # Follow-up MBID detail lookup (has releases)
    mb_detail_resp = MagicMock()
    mb_detail_resp.status_code = 200
    mb_detail_resp.json.return_value = {
        "releases": [{"title": "Album"}],
        "life-span": {"begin": "2015"},
    }
    with patch("requests.get", side_effect=[search_resp, lastfm_resp, mb_search_resp, mb_detail_resp]):
        with patch("time.sleep"):  # skip rate-limit sleeps in test
            result = md.fetch_filter_data("fake band", "fake_key")
    assert result["mb_type"] == "Group"
    assert result["mb_has_releases"] is True
    assert result["debut_year"] == 2015


def test_fetch_filter_data_mb_search_rejects_low_score():
    """MusicBrainz search results with score < 80 are treated as not found."""
    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = {
        "results": {"artistmatches": {"artist": [{"name": "AI Bot"}]}}
    }
    lastfm_resp = MagicMock()
    lastfm_resp.status_code = 200
    lastfm_resp.json.return_value = {
        "artist": {
            "stats": {"listeners": "10"},
            "mbid": "",
            "bio": {"content": ""},
            "tags": {"tag": []},
        }
    }
    mb_search_resp = MagicMock()
    mb_search_resp.status_code = 200
    mb_search_resp.json.return_value = {
        "artists": [{"name": "AI Bot X", "score": 50, "type": "Person"}]
    }
    with patch("requests.get", side_effect=[search_resp, lastfm_resp, mb_search_resp]):
        with patch("time.sleep"):
            result = md.fetch_filter_data("ai bot", "fake_key")
    assert result.get("mb_type") is None
    assert result.get("mb_has_releases") is False


def test_fetch_filter_data_mb_search_rejects_name_mismatch():
    """MusicBrainz search result with wrong name is treated as not found."""
    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = {
        "results": {"artistmatches": {"artist": [{"name": "Elena Veil"}]}}
    }
    lastfm_resp = MagicMock()
    lastfm_resp.status_code = 200
    lastfm_resp.json.return_value = {
        "artist": {
            "stats": {"listeners": "50"},
            "mbid": "",
            "bio": {"content": ""},
            "tags": {"tag": []},
        }
    }
    mb_search_resp = MagicMock()
    mb_search_resp.status_code = 200
    mb_search_resp.json.return_value = {
        "artists": [{"name": "Elena", "score": 90, "type": "Person"}]
    }
    with patch("requests.get", side_effect=[search_resp, lastfm_resp, mb_search_resp]):
        with patch("time.sleep"):
            result = md.fetch_filter_data("elena veil", "fake_key")
    assert result.get("mb_type") is None


def test_fetch_filter_data_bio_strips_lastfm_boilerplate():
    """Bio length excludes the standard Last.fm 'Read more' suffix and HTML."""
    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = {
        "results": {"artistmatches": {"artist": [{"name": "Test"}]}}
    }
    lastfm_resp = MagicMock()
    lastfm_resp.status_code = 200
    lastfm_resp.json.return_value = {
        "artist": {
            "stats": {"listeners": "100"},
            "mbid": "",
            "bio": {"content": '<a href="https://www.last.fm/music/Test">Read more on Last.fm</a>'},
            "tags": {"tag": []},
        }
    }
    mb_search_resp = MagicMock()
    mb_search_resp.status_code = 200
    mb_search_resp.json.return_value = {"artists": []}
    with patch("requests.get", side_effect=[search_resp, lastfm_resp, mb_search_resp]):
        result = md.fetch_filter_data("test", "fake_key")
    assert result["bio_length"] == 0


def test_fetch_filter_data_returns_similar_artists(monkeypatch):
    """fetch_filter_data extracts similar artists from getInfo response."""
    search_json = {"results": {"artistmatches": {"artist": [{"name": "Opeth"}]}}}
    getinfo_json = {
        "artist": {
            "stats": {"listeners": "500000"},
            "mbid": "",
            "bio": {"content": "Swedish band"},
            "tags": {"tag": [{"name": "metal"}]},
            "similar": {
                "artist": [
                    {"name": "Katatonia", "match": "0.85"},
                    {"name": "Porcupine Tree", "match": "0.72"},
                ]
            },
        }
    }

    call_count = {"n": 0}
    def mock_get(url, **kwargs):
        call_count["n"] += 1
        resp = type("R", (), {"status_code": 200})()
        if call_count["n"] == 1:
            resp.json = lambda: search_json
        else:
            resp.json = lambda: getinfo_json
        return resp

    monkeypatch.setattr("music_discovery.requests.get", mock_get)
    monkeypatch.setattr("music_discovery.time.sleep", lambda x: None)

    result = md.fetch_filter_data("opeth", "fake_key")
    assert "similar_artists" in result
    assert result["similar_artists"] == [
        {"name": "Katatonia", "match": 0.85},
        {"name": "Porcupine Tree", "match": 0.72},
    ]


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


# ── filter_candidates with AI detection ───────────────────

def test_filter_candidates_blocks_ai_static(monkeypatch):
    """Rule 4 blocks artists on the AI static blocklist."""
    monkeypatch.setattr(md, "ARTIST_BLOCKLIST", set())
    scored = [(10.0, "elena veil"), (8.0, "real band")]
    cache = {
        "elena veil": {"listeners": 5000, "debut_year": 2020},
        "real band": {"listeners": 5000, "debut_year": 2020},
    }
    result = md.filter_candidates(
        scored, cache,
        ai_blocklist={"elena veil"}, ai_allowlist=set())
    names = [name for _, name in result]
    assert "elena veil" not in names
    assert "real band" in names


def test_filter_candidates_ai_allowlist_overrides_blocklist(monkeypatch):
    """AI allowlist prevents blocking even if on AI blocklist."""
    monkeypatch.setattr(md, "ARTIST_BLOCKLIST", set())
    scored = [(10.0, "mayhem")]
    cache = {"mayhem": {"listeners": 5000, "debut_year": 1984}}
    result = md.filter_candidates(
        scored, cache,
        ai_blocklist={"mayhem"}, ai_allowlist={"mayhem"})
    assert len(result) == 1


def test_filter_candidates_blocks_ai_metadata(monkeypatch):
    """Rule 4 blocks artists that fail the metadata heuristic."""
    monkeypatch.setattr(md, "ARTIST_BLOCKLIST", set())
    scored = [(5.0, "ai filler")]
    cache = {"ai filler": {
        "listeners": 50, "debut_year": None, "bio_length": 0,
        "tag_count": 0, "mb_type": None, "mb_has_releases": False,
    }}
    result = md.filter_candidates(
        scored, cache,
        ai_blocklist=set(), ai_allowlist=set())
    assert len(result) == 0


def test_filter_candidates_no_ai_args_skips_rule4(monkeypatch):
    """When ai_blocklist/ai_allowlist are not passed, Rule 4 is skipped (backward compat)."""
    monkeypatch.setattr(md, "ARTIST_BLOCKLIST", set())
    scored = [(5.0, "elena veil")]
    cache = {"elena veil": {"listeners": 50, "bio_length": 0, "tag_count": 0}}
    result = md.filter_candidates(scored, cache)
    # No AI args → no Rule 4 → artist passes
    assert len(result) == 1


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
        "json": lambda self: {"resultCount": 1, "results": [{"trackId": 12345, "kind": "song"}]},
    })()
    monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)
    assert md.search_itunes("Radiohead", "Creep") == "12345"

def test_search_itunes_filters_music_videos(monkeypatch):
    """Skips music videos and returns only songs."""
    mock_resp = type("R", (), {
        "status_code": 200,
        "json": lambda self: {"resultCount": 2, "results": [
            {"trackId": 111, "kind": "music-video", "artistName": "Radiohead"},
            {"trackId": 222, "kind": "song", "artistName": "Radiohead"},
        ]},
    })()
    monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)
    assert md.search_itunes("Radiohead", "Creep") == "222"

def test_search_itunes_returns_none_when_only_videos(monkeypatch):
    """Returns None when all results are music videos."""
    mock_resp = type("R", (), {
        "status_code": 200,
        "json": lambda self: {"resultCount": 1, "results": [
            {"trackId": 111, "kind": "music-video", "artistName": "Radiohead"},
        ]},
    })()
    monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)
    assert md.search_itunes("Radiohead", "Creep") is None

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

def test_setup_playlist_creates_if_missing(monkeypatch):
    """Returns True and creates playlist when it doesn't exist."""
    responses = iter([("-1", 0), ("", 0)])
    monkeypatch.setattr(md, "_run_applescript", lambda script: next(responses))
    assert md.setup_playlist() is True

def test_setup_playlist_returns_false_on_failure(monkeypatch):
    """Returns False when osascript fails."""
    monkeypatch.setattr(md, "_run_applescript", lambda script: ("error", 1))
    assert md.setup_playlist() is False

def test_setup_playlist_deletes_and_recreates_nonempty(monkeypatch):
    """Non-empty playlist is deleted and recreated (not just cleared)."""
    scripts_called = []
    responses = iter([
        ("25", 0),   # count query — 25 tracks exist
        ("", 0),     # delete playlist
        ("", 0),     # create new playlist
    ])
    def fake_run(script):
        scripts_called.append(script)
        return next(responses)
    monkeypatch.setattr(md, "_run_applescript", fake_run)
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert md.setup_playlist() is True
    assert "delete user playlist" in scripts_called[1]
    assert "delete tracks" not in scripts_called[1]

def test_setup_playlist_empty_playlist_is_noop(monkeypatch):
    """Already-empty playlist returns True without any delete or create."""
    call_count = [0]
    def fake_run(script):
        call_count[0] += 1
        return ("0", 0)
    monkeypatch.setattr(md, "_run_applescript", fake_run)
    assert md.setup_playlist() is True
    assert call_count[0] == 1

def test_setup_playlist_delete_failure_returns_false(monkeypatch):
    """Returns False when deleting existing playlist fails."""
    responses = iter([
        ("10", 0),    # count query — 10 tracks exist
        ("error", 1), # delete fails
    ])
    monkeypatch.setattr(md, "_run_applescript", lambda script: next(responses))
    monkeypatch.setattr("time.sleep", lambda s: None)
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
    """Returns True when track is found in library and added to playlist."""
    monkeypatch.setattr(md, "search_itunes", lambda a, t: "12345")
    monkeypatch.setattr(md, "_play_store_track", lambda sid: True)
    responses = iter([
        ("not_found", 0),          # dedup check
        ("Old|||Track", 0),        # snapshot current track
        ("Creep|||Radiohead", 0),  # poll — different from snapshot
        ("Creep|||Radiohead", 0),  # track info capture
        ("ok_library:Creep|||Radiohead", 0),  # library search + playlist add
    ])
    monkeypatch.setattr(md, "_run_applescript", lambda script: next(responses))
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert md.add_track_to_playlist("Radiohead", "Creep") is True

def test_add_track_to_playlist_returns_false_when_not_on_apple_music(monkeypatch):
    """Returns False when iTunes Search API finds nothing."""
    monkeypatch.setattr(md, "search_itunes", lambda a, t: None)
    responses = iter([("not_found", 0)])  # dedup check
    monkeypatch.setattr(md, "_run_applescript", lambda script: next(responses))
    assert md.add_track_to_playlist("Nobody", "Fake Song") is False

def test_add_track_to_playlist_raises_on_osascript_failure(monkeypatch):
    """Raises RuntimeError when osascript returns non-zero."""
    monkeypatch.setattr(md, "search_itunes", lambda a, t: "12345")
    monkeypatch.setattr(md, "_play_store_track", lambda sid: True)
    responses = iter([
        ("not_found", 0),          # dedup check
        ("Old|||Track", 0),        # snapshot
        ("Creep|||Radiohead", 0),  # poll — breaks loop
        ("Creep|||Radiohead", 0),  # track info capture
        ("", 1),                   # library search fails
    ])
    monkeypatch.setattr(md, "_run_applescript", lambda script: next(responses))
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        md.add_track_to_playlist("Radiohead", "Creep")

def test_add_track_not_in_library_uses_split_add(monkeypatch):
    """When track is not in library, uses separate library-add then playlist-add."""
    monkeypatch.setattr(md, "search_itunes", lambda a, t: "12345")
    monkeypatch.setattr(md, "_play_store_track", lambda sid: True)
    responses = iter([
        ("not_found", 0),          # dedup check
        ("Old|||Track", 0),        # snapshot
        ("Creep|||Radiohead", 0),  # poll
        ("Creep|||Radiohead", 0),  # track info capture
        ("not_in_library", 0),     # library search — not found
        ("lib_ok", 0),             # separate library add
        ("ok_added:Creep|||Radiohead", 0),  # retry search + playlist add
    ])
    monkeypatch.setattr(md, "_run_applescript", lambda script: next(responses))
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert md.add_track_to_playlist("Radiohead", "Creep") is True


def test_add_track_library_add_retries_on_notfound(monkeypatch):
    """When track added to library but not immediately findable, retries."""
    monkeypatch.setattr(md, "search_itunes", lambda a, t: "12345")
    monkeypatch.setattr(md, "_play_store_track", lambda sid: True)
    responses = iter([
        ("not_found", 0),          # dedup check
        ("Old|||Track", 0),        # snapshot
        ("Creep|||Radiohead", 0),  # poll
        ("Creep|||Radiohead", 0),  # track info capture
        ("not_in_library", 0),     # library search — not found
        ("lib_ok", 0),             # separate library add
        ("notfound_in_library", 0),  # retry 1 — still not indexed
        ("notfound_in_library", 0),  # retry 2 — still not indexed
        ("ok_added:Creep|||Radiohead", 0),  # retry 3 — found!
    ])
    monkeypatch.setattr(md, "_run_applescript", lambda script: next(responses))
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert md.add_track_to_playlist("Radiohead", "Creep") is True


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
    add_count = [0]
    add_calls = []
    def mock_add(artist, track):
        add_calls.append((artist, track))
        add_count[0] += 1
        return True
    monkeypatch.setattr(md, "add_track_to_playlist", mock_add)
    monkeypatch.setattr(md, "_get_playlist_count", lambda: add_count[0])
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
    monkeypatch.setattr(md, "_get_playlist_count", lambda: 0)
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


def test_build_playlist_blocklists_unfindable_artists(monkeypatch, tmp_path):
    """Artists with zero tracks found on Apple Music are added to the blocklist."""
    monkeypatch.setattr(md, "setup_playlist", lambda: True)
    monkeypatch.setattr(md, "_stop_playback", lambda: None)
    monkeypatch.setattr(md, "_get_playlist_count", lambda: 0)
    # All tracks fail to add
    monkeypatch.setattr(md, "add_track_to_playlist", lambda artist, track: False)
    monkeypatch.setattr(md, "load_cache", lambda p: {
        "unfindable": [{"name": "Ghost Song", "artist": "Unfindable"}],
    })
    monkeypatch.setattr(md, "save_cache", lambda c, p: None)
    monkeypatch.setattr(md, "fetch_top_tracks", lambda a, k: [])
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    paths = md._build_paths()
    ranked = [(10.0, "unfindable")]
    success, _ = md.build_playlist(ranked, "fake_key", paths)
    assert success is True

    blocklist = md.load_blocklist(paths["blocklist"])
    assert "unfindable" in blocklist


def test_build_playlist_does_not_blocklist_findable_artists(monkeypatch, tmp_path):
    """Artists with at least one track found are NOT blocklisted."""
    monkeypatch.setattr(md, "setup_playlist", lambda: True)
    monkeypatch.setattr(md, "_stop_playback", lambda: None)
    add_count = [0]
    def mock_add(artist, track):
        add_count[0] += 1
        return True
    monkeypatch.setattr(md, "add_track_to_playlist", mock_add)
    monkeypatch.setattr(md, "_get_playlist_count", lambda: add_count[0])
    monkeypatch.setattr(md, "load_cache", lambda p: {
        "goodartist": [{"name": "Good Song", "artist": "GoodArtist"}],
    })
    monkeypatch.setattr(md, "save_cache", lambda c, p: None)
    monkeypatch.setattr(md, "fetch_top_tracks", lambda a, k: [])
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    paths = md._build_paths()
    ranked = [(10.0, "goodartist")]
    success, _ = md.build_playlist(ranked, "fake_key", paths)
    assert success is True

    blocklist = md.load_blocklist(paths["blocklist"])
    assert "goodartist" not in blocklist


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


# ── load_ai_blocklist / load_ai_allowlist ─────────────────

def test_load_ai_blocklist_reads_names(tmp_path):
    """Reads artist names, lowercased, ignoring comments and blanks."""
    f = tmp_path / "ai_blocklist.txt"
    f.write_text("# comment\nElena Veil\n\nDeep Watch\n")
    result = md.load_ai_blocklist(f)
    assert result == {"elena veil", "deep watch"}

def test_load_ai_blocklist_missing_file(tmp_path):
    """Returns empty set if file does not exist."""
    result = md.load_ai_blocklist(tmp_path / "nope.txt")
    assert result == set()

def test_load_ai_allowlist_reads_names(tmp_path):
    """Reads artist names, lowercased, ignoring comments and blanks."""
    f = tmp_path / "ai_allowlist.txt"
    f.write_text("# override\nMayhem\n")
    result = md.load_ai_allowlist(f)
    assert result == {"mayhem"}

def test_load_ai_allowlist_missing_file(tmp_path):
    """Returns empty set if file does not exist."""
    result = md.load_ai_allowlist(tmp_path / "nope.txt")
    assert result == set()


SAMPLE_PLIST_WITH_PLAYLIST = {
    "Tracks": {
        "100": {"Artist": "Artist A", "Name": "Song 1", "Loved": True, "Play Count": 5},
        "101": {"Artist": "Artist B", "Name": "Song 2", "Play Count": 0},
        "102": {"Artist": "Artist B", "Name": "Song 3"},
        "103": {"Artist": "Artist C", "Name": "Song 4", "Play Count": 2},
        "104": {"Artist": "Artist D", "Name": "Song 5", "Loved": True, "Play Count": 1},
    },
    "Playlists": [
        {"Name": "Library", "Playlist Items": [
            {"Track ID": 100}, {"Track ID": 101}, {"Track ID": 102},
            {"Track ID": 103}, {"Track ID": 104},
        ]},
        {"Name": "Music Discovery", "Playlist Items": [
            {"Track ID": 101}, {"Track ID": 102}, {"Track ID": 103},
        ]},
    ],
}

def test_parse_md_playlist_finds_tracks():
    result = md.parse_md_playlist(SAMPLE_PLIST_WITH_PLAYLIST)
    assert result is not None
    artists, total, unplayed = result
    assert total == 3
    assert "artist b" in artists
    assert "artist c" in artists

def test_parse_md_playlist_counts_unplayed():
    result = md.parse_md_playlist(SAMPLE_PLIST_WITH_PLAYLIST)
    artists, total, unplayed = result
    assert unplayed == 2

def test_parse_md_playlist_returns_none_when_missing():
    result = md.parse_md_playlist({"Tracks": {}, "Playlists": [{"Name": "Other"}]})
    assert result is None

def test_parse_md_playlist_returns_none_when_empty():
    result = md.parse_md_playlist({"Tracks": {}, "Playlists": [
        {"Name": "Music Discovery", "Playlist Items": []}
    ]})
    assert result is None

def test_parse_md_playlist_artist_names_lowercased():
    result = md.parse_md_playlist(SAMPLE_PLIST_WITH_PLAYLIST)
    artists, _, _ = result
    for name in artists:
        assert name == name.lower()


def test_audit_blocklists_unfavorited_artists():
    """Artists in MD playlist with no loved tracks should be blocklisted."""
    playlist_artists = {"artist b", "artist c"}
    library_artists = {"artist a": 3, "artist c": 1}  # artist c has loved tracks, b does not
    existing_blocklist = set()
    result = md.audit_md_playlist(
        playlist_artists, library_artists, existing_blocklist,
        total=10, unplayed=2, interactive=False,
    )
    assert "artist b" in result
    assert "artist c" not in result

def test_audit_skips_already_blocklisted():
    """Artists already in the blocklist should not be re-added."""
    playlist_artists = {"artist b", "artist c"}
    library_artists = {}
    existing_blocklist = {"artist b"}
    result = md.audit_md_playlist(
        playlist_artists, library_artists, existing_blocklist,
        total=10, unplayed=2, interactive=False,
    )
    assert "artist b" not in result
    assert "artist c" in result

def test_audit_prompts_when_over_25_percent_unplayed(monkeypatch):
    """If >25% unplayed and user says 'n', return empty set."""
    monkeypatch.setattr('builtins.input', lambda _: 'n')
    playlist_artists = {"artist b"}
    library_artists = {}
    result = md.audit_md_playlist(
        playlist_artists, library_artists, set(),
        total=10, unplayed=5, interactive=True,
    )
    assert result == set()

def test_audit_prompts_when_over_25_percent_user_says_yes(monkeypatch):
    """If >25% unplayed and user says 'y', proceed with blocklisting."""
    monkeypatch.setattr('builtins.input', lambda _: 'y')
    playlist_artists = {"artist b"}
    library_artists = {}
    result = md.audit_md_playlist(
        playlist_artists, library_artists, set(),
        total=10, unplayed=5, interactive=True,
    )
    assert "artist b" in result

def test_audit_no_prompt_when_under_25_percent():
    """If <=25% unplayed, no prompt — just blocklist."""
    playlist_artists = {"artist b"}
    library_artists = {}
    result = md.audit_md_playlist(
        playlist_artists, library_artists, set(),
        total=10, unplayed=2, interactive=True,
    )
    assert "artist b" in result

def test_audit_skips_in_non_interactive_mode_when_over_25():
    """Non-interactive + >25% unplayed → safe default: skip blocklisting."""
    playlist_artists = {"artist b"}
    library_artists = {}
    result = md.audit_md_playlist(
        playlist_artists, library_artists, set(),
        total=10, unplayed=5, interactive=False,
    )
    assert result == set()


def test_main_runs_playlist_audit(tmp_path, monkeypatch):
    """Verify main() calls audit and adds rejected artists to blocklist."""
    plist_data = {
        "Tracks": {
            "1": {"Artist": "Loved One", "Loved": True, "Favorited": True},
            "2": {"Artist": "Rejected", "Name": "Song", "Play Count": 3},
        },
        "Playlists": [
            {"Name": "Music Discovery", "Playlist Items": [{"Track ID": 2}]},
        ],
    }
    lib_path = tmp_path / "Library.xml"
    lib_path.write_bytes(plistlib.dumps(plist_data))

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    monkeypatch.setattr('sys.argv', ['music_discovery.py', '--library', str(lib_path)])
    monkeypatch.setenv('CACHE_DIR', str(cache_dir))
    monkeypatch.setenv('OUTPUT_DIR', str(cache_dir))
    monkeypatch.setenv('LASTFM_API_KEY', 'dummy_key_for_test_00000000000')
    # Skip interactive API key prompt
    monkeypatch.setattr(md, 'prompt_for_api_key', lambda *a, **kw: None)
    # Provide a scraper that returns no similar artists (fast)
    monkeypatch.setattr(md, 'detect_scraper', lambda: lambda artist: {})
    # Skip network calls for filter data
    monkeypatch.setattr(md, 'fetch_filter_data', lambda *a, **kw: {})
    # Mock AppleScript to say playlist exists (so audit runs against XML data)
    monkeypatch.setattr(md, '_run_applescript', lambda script: ("yes", 0))

    md.main()

    # Check that 'rejected' was added to blocklist_cache.json
    import json
    blocklist_path = cache_dir / "blocklist_cache.json"
    assert blocklist_path.exists(), "blocklist_cache.json should have been created"
    data = json.loads(blocklist_path.read_text())
    assert "rejected" in data.get("blocked", [])


def test_main_excludes_md_playlist_artists_from_results(tmp_path, monkeypatch):
    """Artists from an existing MD playlist are excluded from current run results,
    even without permanent blocklisting (e.g. when >25% unplayed, non-interactive)."""
    plist_data = {
        "Tracks": {
            "1": {"Artist": "Loved One", "Loved": True},
            "2": {"Artist": "Old Discovery", "Name": "Song", "Play Count": 0},
            "3": {"Artist": "Another Old", "Name": "Song2", "Play Count": 0},
        },
        "Playlists": [
            {"Name": "Music Discovery", "Playlist Items": [
                {"Track ID": 2}, {"Track ID": 3},
            ]},
        ],
    }
    lib_path = tmp_path / "Library.xml"
    lib_path.write_bytes(plistlib.dumps(plist_data))

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    # Seed the scrape cache so "old discovery" and "another old" appear as candidates
    scrape_cache = {
        "loved one": {
            "old discovery": 0.9,
            "another old": 0.8,
            "brand new": 0.7,
        }
    }
    (cache_dir / "music_map_cache.json").write_text(json.dumps(scrape_cache))

    monkeypatch.setattr('sys.argv', ['music_discovery.py', '--library', str(lib_path)])
    monkeypatch.setenv('CACHE_DIR', str(cache_dir))
    monkeypatch.setenv('OUTPUT_DIR', str(cache_dir))
    monkeypatch.setenv('LASTFM_API_KEY', 'dummy_key_for_test_00000000000')
    monkeypatch.setattr(md, 'prompt_for_api_key', lambda *a, **kw: None)
    monkeypatch.setattr(md, 'detect_scraper', lambda: lambda artist: {})
    # Return valid filter data so candidates aren't auto-blocked as non-artists
    monkeypatch.setattr(md, 'fetch_filter_data',
                        lambda *a, **kw: {"listeners": 10000, "debut_year": 2020})
    # Mock AppleScript to say playlist exists (so audit runs against XML data)
    monkeypatch.setattr(md, '_run_applescript', lambda script: ("yes", 0))

    md.main()

    # Read the output results
    results_path = cache_dir / "music_discovery_results.txt"
    assert results_path.exists()
    content = results_path.read_text()
    # MD playlist artists should NOT appear in results
    assert "old discovery" not in content
    assert "another old" not in content
    # Genuinely new artists should still appear
    assert "brand new" in content


def test_main_md_exclusion_does_not_persist_to_blocklist(tmp_path, monkeypatch):
    """MD playlist exclusion is per-run only — artists are NOT saved to blocklist."""
    plist_data = {
        "Tracks": {
            "1": {"Artist": "Loved One", "Loved": True},
            "2": {"Artist": "Old Discovery", "Name": "Song", "Play Count": 0},
        },
        "Playlists": [
            {"Name": "Music Discovery", "Playlist Items": [{"Track ID": 2}]},
        ],
    }
    lib_path = tmp_path / "Library.xml"
    lib_path.write_bytes(plistlib.dumps(plist_data))

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    monkeypatch.setattr('sys.argv', ['music_discovery.py', '--library', str(lib_path)])
    monkeypatch.setenv('CACHE_DIR', str(cache_dir))
    monkeypatch.setenv('OUTPUT_DIR', str(cache_dir))
    monkeypatch.setenv('LASTFM_API_KEY', 'dummy_key_for_test_00000000000')
    monkeypatch.setattr(md, 'prompt_for_api_key', lambda *a, **kw: None)
    monkeypatch.setattr(md, 'detect_scraper', lambda: lambda artist: {})
    # Return valid filter data so auto-blocklist detection doesn't interfere
    monkeypatch.setattr(md, 'fetch_filter_data',
                        lambda *a, **kw: {"listeners": 10000, "debut_year": 2020})

    # Seed blocklist with a known entry so the file is always written
    blocklist_path = cache_dir / "blocklist_cache.json"
    blocklist_path.write_text(json.dumps({"blocked": ["pre-existing"]}))
    # Mock AppleScript to say playlist exists (so audit runs against XML data)
    monkeypatch.setattr(md, '_run_applescript', lambda script: ("yes", 0))

    md.main()

    # "old discovery" was excluded from results but should NOT be in the blocklist
    assert blocklist_path.exists()
    data = json.loads(blocklist_path.read_text())
    assert "pre-existing" in data.get("blocked", []), "seed entry should survive"
    assert "old discovery" not in data.get("blocked", []), \
        "MD playlist exclusion should not persist to blocklist"


def test_build_playlist_aborts_on_sync_loop(monkeypatch, tmp_path):
    """If playlist count exceeds expected, build_playlist detects sync loop and aborts."""
    monkeypatch.setattr(md, "setup_playlist", lambda: True)
    monkeypatch.setattr(md, "_stop_playback", lambda: None)
    deleted = []
    orig_run = md._run_applescript
    def mock_run(script):
        if "delete user playlist" in script:
            deleted.append(True)
            return ("", 0)
        return orig_run(script)
    monkeypatch.setattr(md, "_run_applescript", mock_run)

    add_count = [0]
    def mock_add(artist, track):
        add_count[0] += 1
        return True
    monkeypatch.setattr(md, "add_track_to_playlist", mock_add)
    # Simulate sync loop: playlist count grows much faster than adds
    monkeypatch.setattr(md, "_get_playlist_count", lambda: add_count[0] * 100)

    # Need enough artists/tracks to trigger the check (every 10 adds)
    cache = {}
    for i in range(20):
        name = f"artist{i}"
        cache[name] = [{"name": f"Song{i}", "artist": name.title()}]
    monkeypatch.setattr(md, "load_cache", lambda p: cache)
    monkeypatch.setattr(md, "save_cache", lambda c, p: None)
    monkeypatch.setattr(md, "fetch_top_tracks", lambda a, k: [])
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    paths = md._build_paths()
    ranked = [(10.0 - i * 0.1, f"artist{i}") for i in range(20)]
    success, _ = md.build_playlist(ranked, "fake_key", paths)
    assert success is False
    assert len(deleted) > 0  # playlist was deleted


def test_build_playlist_final_verify_catches_late_sync(monkeypatch, tmp_path):
    """Final verification catches sync issues that develop after adds complete."""
    monkeypatch.setattr(md, "setup_playlist", lambda: True)
    monkeypatch.setattr(md, "_stop_playback", lambda: None)
    deleted = []
    orig_run = md._run_applescript
    def mock_run(script):
        if "delete user playlist" in script:
            deleted.append(True)
            return ("", 0)
        return orig_run(script)
    monkeypatch.setattr(md, "_run_applescript", mock_run)

    monkeypatch.setattr(md, "add_track_to_playlist", lambda a, t: True)
    # Final verify sees a huge count — simulates late sync explosion
    monkeypatch.setattr(md, "_get_playlist_count", lambda: 5000)

    cache = {"artist0": [{"name": "Song0", "artist": "Artist0"}]}
    monkeypatch.setattr(md, "load_cache", lambda p: cache)
    monkeypatch.setattr(md, "save_cache", lambda c, p: None)
    monkeypatch.setattr(md, "fetch_top_tracks", lambda a, k: [])
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    paths = md._build_paths()
    ranked = [(10.0, "artist0")]
    success, _ = md.build_playlist(ranked, "fake_key", paths)
    assert success is False
    assert len(deleted) > 0


def test_add_track_no_combined_library_and_playlist(monkeypatch):
    """Verify library-add and playlist-add are never in the same AppleScript call."""
    monkeypatch.setattr(md, "search_itunes", lambda a, t: "12345")
    monkeypatch.setattr(md, "_play_store_track", lambda sid: True)
    scripts = []
    responses = iter([
        ("not_found", 0),
        ("Old|||Track", 0),
        ("Creep|||Radiohead", 0),
        ("Creep|||Radiohead", 0),
        ("not_in_library", 0),  # library search — not found
        ("lib_ok", 0),          # separate library add
        ("ok_added:Creep|||Radiohead", 0),  # retry search + playlist add
    ])
    def capture_script(script):
        scripts.append(script)
        return next(responses)
    monkeypatch.setattr(md, "_run_applescript", capture_script)
    monkeypatch.setattr("time.sleep", lambda s: None)
    md.add_track_to_playlist("Radiohead", "Creep")
    # No single script should contain BOTH library add AND playlist add
    for script in scripts:
        has_lib_add = 'duplicate ct to source "Library"' in script
        has_pl_add = 'duplicate t to user playlist' in script
        assert not (has_lib_add and has_pl_add), \
            "Library-add and playlist-add must be in separate AppleScript calls"


def test_add_track_library_path(monkeypatch):
    """When track IS in library, add_track_to_playlist uses library copy."""
    monkeypatch.setattr(md, "search_itunes", lambda a, t: "12345")
    monkeypatch.setattr(md, "_play_store_track", lambda sid: True)
    responses = iter([
        ("not_found", 0),
        ("Old|||Track", 0),
        ("Creep|||Radiohead", 0),
        ("Creep|||Radiohead", 0),
        ("ok_library:Creep|||Radiohead", 0),
    ])
    monkeypatch.setattr(md, "_run_applescript", lambda script: next(responses))
    monkeypatch.setattr("time.sleep", lambda s: None)
    result = md.add_track_to_playlist("Radiohead", "Creep")
    assert result is True


# ── JXA library reading tests ────────────────────────────────

def test_parse_library_jxa_basic():
    jxa_output = json.dumps(["Tom Waits", "Radiohead", "Tom Waits", "Tom Waits"])
    with patch.object(md, "_run_jxa", return_value=(jxa_output, 0)):
        result = md.parse_library_jxa()
    assert result == {"tom waits": 3, "radiohead": 1}

def test_parse_library_jxa_empty_library():
    jxa_output = json.dumps([])
    with patch.object(md, "_run_jxa", return_value=(jxa_output, 0)):
        result = md.parse_library_jxa()
    assert result == {}

def test_parse_library_jxa_case_folding():
    jxa_output = json.dumps(["Radiohead", "RADIOHEAD", "radiohead"])
    with patch.object(md, "_run_jxa", return_value=(jxa_output, 0)):
        result = md.parse_library_jxa()
    assert result == {"radiohead": 3}

def test_parse_library_jxa_strips_whitespace():
    jxa_output = json.dumps(["  Tom Waits  ", "Tom Waits"])
    with patch.object(md, "_run_jxa", return_value=(jxa_output, 0)):
        result = md.parse_library_jxa()
    assert result == {"tom waits": 2}

def test_parse_library_jxa_skips_empty_artists():
    jxa_output = json.dumps(["Tom Waits", "", "  ", "Radiohead"])
    with patch.object(md, "_run_jxa", return_value=(jxa_output, 0)):
        result = md.parse_library_jxa()
    assert result == {"tom waits": 1, "radiohead": 1}

def test_parse_library_jxa_nonzero_exit():
    with patch.object(md, "_run_jxa", return_value=("", 1)):
        with pytest.raises(RuntimeError, match="JXA library read failed"):
            md.parse_library_jxa()

def test_parse_library_jxa_invalid_json():
    with patch.object(md, "_run_jxa", return_value=("not json at all", 0)):
        with pytest.raises(RuntimeError, match="Failed to parse JXA output"):
            md.parse_library_jxa()

def test_parse_library_jxa_timeout():
    with patch.object(md, "_run_jxa", side_effect=RuntimeError("osascript (JXA) timed out after 30 seconds")):
        with pytest.raises(RuntimeError, match="timed out"):
            md.parse_library_jxa()


# ── JXA playlist reading tests ────────────────────────────────

def test_parse_md_playlist_jxa_basic():
    jxa_output = json.dumps({
        "tracks": [
            {"artist": "Nick Cave", "playCount": 5},
            {"artist": "Leonard Cohen", "playCount": 0},
            {"artist": "PJ Harvey", "playCount": 3},
            {"artist": "Nick Cave", "playCount": 2},
        ]
    })
    with patch.object(md, "_run_jxa", return_value=(jxa_output, 0)):
        result = md.parse_md_playlist_jxa()
    artists, total, unplayed = result
    assert artists == {"nick cave", "leonard cohen", "pj harvey"}
    assert total == 4
    assert unplayed == 1

def test_parse_md_playlist_jxa_all_unplayed():
    jxa_output = json.dumps({
        "tracks": [
            {"artist": "A", "playCount": 0},
            {"artist": "B", "playCount": 0},
        ]
    })
    with patch.object(md, "_run_jxa", return_value=(jxa_output, 0)):
        artists, total, unplayed = md.parse_md_playlist_jxa()
    assert total == 2
    assert unplayed == 2

def test_parse_md_playlist_jxa_no_playlist():
    jxa_output = "null"
    with patch.object(md, "_run_jxa", return_value=(jxa_output, 0)):
        result = md.parse_md_playlist_jxa()
    assert result is None

def test_parse_md_playlist_jxa_empty_playlist():
    jxa_output = json.dumps({"tracks": []})
    with patch.object(md, "_run_jxa", return_value=(jxa_output, 0)):
        result = md.parse_md_playlist_jxa()
    assert result is None

def test_parse_md_playlist_jxa_nonzero_exit():
    with patch.object(md, "_run_jxa", return_value=("error text", 1)):
        with pytest.raises(RuntimeError, match="JXA playlist read failed"):
            md.parse_md_playlist_jxa()

def test_parse_md_playlist_jxa_invalid_json():
    with patch.object(md, "_run_jxa", return_value=("broken{json", 0)):
        with pytest.raises(RuntimeError, match="Failed to parse JXA playlist output"):
            md.parse_md_playlist_jxa()

def test_parse_md_playlist_jxa_skips_empty_artists():
    jxa_output = json.dumps({
        "tracks": [
            {"artist": "Nick Cave", "playCount": 1},
            {"artist": "", "playCount": 0},
        ]
    })
    with patch.object(md, "_run_jxa", return_value=(jxa_output, 0)):
        artists, total, unplayed = md.parse_md_playlist_jxa()
    assert artists == {"nick cave"}
    assert total == 2
    assert unplayed == 1


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


# ── check_ai_artist ───────────────────────────────────────

import datetime  # needed for TTL boundary tests

AI_BL = {"elena veil", "deep watch"}
AI_AL = {"mayhem"}

def test_check_ai_artist_allowlist_overrides():
    """Artist in allowlist always passes, even if in blocklist."""
    blocked, reason = md.check_ai_artist("mayhem", {}, {"mayhem"}, {"mayhem"})
    assert blocked is False
    assert reason == "allowlist"

def test_check_ai_artist_static_blocklist():
    """Artist in static blocklist is blocked."""
    blocked, reason = md.check_ai_artist("elena veil", {}, AI_BL, set())
    assert blocked is True
    assert reason == "blocked_static"

def test_check_ai_artist_static_blocklist_overrides_cache():
    """Static blocklist blocks even if cache says pass."""
    entry = {"ai_check": "pass", "ai_check_date": "2026-01-01"}
    blocked, reason = md.check_ai_artist("elena veil", entry, AI_BL, set())
    assert blocked is True
    assert reason == "blocked_static"

def test_check_ai_artist_cache_hit_pass():
    """Cached pass is returned without further checks."""
    entry = {"ai_check": "pass", "ai_check_date": datetime.date.today().isoformat()}
    blocked, reason = md.check_ai_artist("some artist", entry, AI_BL, set())
    assert blocked is False
    assert reason == "pass"

def test_check_ai_artist_cache_hit_whitelisted():
    """Cached whitelisted_mb is returned."""
    entry = {"ai_check": "whitelisted_mb", "ai_check_date": datetime.date.today().isoformat()}
    blocked, reason = md.check_ai_artist("real band", entry, AI_BL, set())
    assert blocked is False
    assert reason == "whitelisted_mb"

def test_check_ai_artist_cache_blocked_metadata_expired():
    """Expired blocked_metadata (>90 days) is re-evaluated."""
    expired_date = (datetime.date.today() - datetime.timedelta(days=91)).isoformat()
    entry = {
        "ai_check": "blocked_metadata", "ai_check_date": expired_date,
        "listeners": 500, "bio_length": 0, "tag_count": 0,
        "mb_type": None, "mb_has_releases": False,
    }
    blocked, reason = md.check_ai_artist("old block", entry, set(), set())
    # Re-evaluated: still meets block criteria
    assert blocked is True
    assert reason == "blocked_metadata"

def test_check_ai_artist_cache_blocked_metadata_fresh():
    """Fresh blocked_metadata (<90 days) is returned from cache."""
    fresh_date = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    entry = {
        "ai_check": "blocked_metadata", "ai_check_date": fresh_date,
    }
    blocked, reason = md.check_ai_artist("recent block", entry, set(), set())
    assert blocked is True
    assert reason == "blocked_metadata"

def test_check_ai_artist_cache_blocked_metadata_boundary_day89():
    """blocked_metadata at exactly 89 days is still fresh (< 90)."""
    day89 = (datetime.date.today() - datetime.timedelta(days=89)).isoformat()
    entry = {"ai_check": "blocked_metadata", "ai_check_date": day89}
    blocked, reason = md.check_ai_artist("boundary", entry, set(), set())
    assert blocked is True
    assert reason == "blocked_metadata"

def test_check_ai_artist_cache_blocked_metadata_boundary_day90():
    """blocked_metadata at exactly 90 days expires and re-evaluates."""
    day90 = (datetime.date.today() - datetime.timedelta(days=90)).isoformat()
    entry = {
        "ai_check": "blocked_metadata", "ai_check_date": day90,
        "listeners": 5000, "bio_length": 200, "tag_count": 3,
        "mb_type": None, "mb_has_releases": False,
    }
    blocked, reason = md.check_ai_artist("boundary90", entry, set(), set())
    # Re-evaluated: now has good metadata → passes
    assert blocked is False
    assert reason == "pass"

def test_check_ai_artist_mb_group_with_releases_whitelists():
    """MusicBrainz Group with releases → whitelisted."""
    entry = {"mb_type": "Group", "mb_has_releases": True,
             "listeners": 50, "bio_length": 0, "tag_count": 0}
    blocked, reason = md.check_ai_artist("real band", entry, set(), set())
    assert blocked is False
    assert reason == "whitelisted_mb"
    assert entry["ai_check"] == "whitelisted_mb"

def test_check_ai_artist_mb_person_with_releases_whitelists():
    """MusicBrainz Person with releases → whitelisted."""
    entry = {"mb_type": "Person", "mb_has_releases": True,
             "listeners": 50, "bio_length": 0, "tag_count": 0}
    blocked, reason = md.check_ai_artist("solo artist", entry, set(), set())
    assert blocked is False
    assert reason == "whitelisted_mb"

def test_check_ai_artist_mb_type_without_releases_not_whitelisted():
    """MusicBrainz entry without releases does not whitelist."""
    entry = {"mb_type": "Group", "mb_has_releases": False,
             "listeners": 50, "bio_length": 0, "tag_count": 0}
    blocked, reason = md.check_ai_artist("empty mb", entry, set(), set())
    # Falls through to L3 heuristic: listeners < 1000, no bio, no tags → block
    assert blocked is True
    assert reason == "blocked_metadata"

def test_check_ai_artist_metadata_heuristic_blocks():
    """No MB, low listeners, no bio, no tags → blocked."""
    entry = {"listeners": 50, "bio_length": 0, "tag_count": 0,
             "mb_type": None, "mb_has_releases": False}
    blocked, reason = md.check_ai_artist("ai filler", entry, set(), set())
    assert blocked is True
    assert reason == "blocked_metadata"

def test_check_ai_artist_metadata_heuristic_passes_with_bio():
    """Has bio → passes even with low listeners and no tags."""
    entry = {"listeners": 50, "bio_length": 200, "tag_count": 0,
             "mb_type": None, "mb_has_releases": False}
    blocked, reason = md.check_ai_artist("real obscure", entry, set(), set())
    assert blocked is False
    assert reason == "pass"

def test_check_ai_artist_metadata_heuristic_passes_with_listeners():
    """Listeners >= 1000 → passes even with no bio and no tags."""
    entry = {"listeners": 5000, "bio_length": 0, "tag_count": 0,
             "mb_type": None, "mb_has_releases": False}
    blocked, reason = md.check_ai_artist("popular enough", entry, set(), set())
    assert blocked is False
    assert reason == "pass"

def test_check_ai_artist_empty_entry_passes():
    """Empty filter entry (API failure) → pass (benefit of doubt)."""
    blocked, reason = md.check_ai_artist("unknown", {}, set(), set())
    assert blocked is False
    assert reason == "pass"

def test_check_ai_artist_case_insensitive():
    """Mixed-case name is lowercased before checking blocklist."""
    blocked, reason = md.check_ai_artist("Elena Veil", {}, {"elena veil"}, set())
    assert blocked is True
    assert reason == "blocked_static"

def test_check_ai_artist_malformed_date():
    """Malformed ai_check_date triggers re-evaluation, not crash."""
    entry = {
        "ai_check": "blocked_metadata", "ai_check_date": "not-a-date",
        "listeners": 500, "bio_length": 0, "tag_count": 0,
        "mb_type": None, "mb_has_releases": False,
    }
    blocked, reason = md.check_ai_artist("bad date", entry, set(), set())
    assert blocked is True
    assert reason == "blocked_metadata"

def test_check_ai_artist_static_blocklist_does_not_cache():
    """Static blocklist hit does not write ai_check to cache entry."""
    entry = {"listeners": 5000}
    blocked, reason = md.check_ai_artist("elena veil", entry, {"elena veil"}, set())
    assert blocked is True
    assert "ai_check" not in entry

def test_check_ai_artist_allowlist_overrides_metadata_heuristic():
    """Allowlisted artist passes even if metadata would block them."""
    entry = {"listeners": 10, "bio_length": 0, "tag_count": 0,
             "mb_type": None, "mb_has_releases": False}
    blocked, reason = md.check_ai_artist("my fave", entry, set(), {"my fave"})
    assert blocked is False

def test_check_ai_artist_mb_orchestra_whitelists():
    """MusicBrainz Orchestra with releases → whitelisted."""
    entry = {"mb_type": "Orchestra", "mb_has_releases": True,
             "listeners": 50, "bio_length": 0, "tag_count": 0}
    blocked, reason = md.check_ai_artist("philharmonic", entry, set(), set())
    assert blocked is False
    assert reason == "whitelisted_mb"

def test_check_ai_artist_writes_ai_check_date():
    """ai_check_date is written alongside ai_check for cache entries."""
    entry = {"mb_type": "Group", "mb_has_releases": True,
             "listeners": 50, "bio_length": 0, "tag_count": 0}
    md.check_ai_artist("real band", entry, set(), set())
    assert entry["ai_check_date"] == datetime.date.today().isoformat()

def test_check_ai_artist_old_cache_entry_no_bio_tag_fields():
    """Pre-AI cache entry with only listeners gets evaluated (defaults to 0)."""
    entry = {"listeners": 500, "debut_year": 2020}
    blocked, reason = md.check_ai_artist("old entry", entry, set(), set())
    assert blocked is True
    assert reason == "blocked_metadata"

def test_ai_detection_end_to_end(monkeypatch):
    """Full pipeline: AI artist blocked, real artist whitelisted, allowlist override works."""
    monkeypatch.setattr(md, "ARTIST_BLOCKLIST", set())
    ai_bl = {"elena veil", "deep watch"}
    ai_al = {"deep watch"}  # override for Deep Watch

    scored = [
        (10.0, "elena veil"),      # AI blocklist → blocked
        (9.0, "deep watch"),       # AI blocklist BUT allowlisted → passes
        (8.0, "real band"),        # MB Group with releases → whitelisted
        (7.0, "ai filler"),        # No MB, no bio, no tags, low listeners → blocked
        (6.0, "obscure real"),     # No MB, but has bio → passes
        (5.0, "api failure"),      # Empty entry (API failure) → passes
    ]
    cache = {
        "elena veil": {"listeners": 50, "bio_length": 0, "tag_count": 0,
                        "mb_type": None, "mb_has_releases": False},
        "deep watch": {"listeners": 50, "bio_length": 0, "tag_count": 0,
                        "mb_type": None, "mb_has_releases": False},
        "real band": {"listeners": 5000, "debut_year": 2020, "bio_length": 200,
                       "tag_count": 3, "mb_type": "Group", "mb_has_releases": True},
        "ai filler": {"listeners": 10, "debut_year": None, "bio_length": 0,
                       "tag_count": 0, "mb_type": None, "mb_has_releases": False},
        "obscure real": {"listeners": 300, "debut_year": None, "bio_length": 150,
                          "tag_count": 0, "mb_type": None, "mb_has_releases": False},
        "api failure": {},
    }
    result = md.filter_candidates(
        scored, cache, ai_blocklist=ai_bl, ai_allowlist=ai_al)
    names = [name for _, name in result]
    assert names == ["deep watch", "real band", "obscure real", "api failure"]


def test_collect_track_metadata_jxa(monkeypatch):
    """collect_track_metadata_jxa returns per-track skip counts, play counts, fave state, dateAdded."""
    import json as _json
    jxa_output = _json.dumps([
        {"name": "Blackwater Park", "artist": "opeth", "playedCount": 15,
         "skippedCount": 2, "favorited": True, "dateAdded": "2024-06-15T10:30:00Z"},
        {"name": "Damnation", "artist": "opeth", "playedCount": 8,
         "skippedCount": 0, "favorited": False, "dateAdded": "2024-06-15T10:30:00Z"},
    ])
    monkeypatch.setattr("music_discovery._run_jxa", lambda script: (jxa_output, 0))

    from music_discovery import collect_track_metadata_jxa
    result = collect_track_metadata_jxa()
    assert len(result) == 2
    assert result[0]["name"] == "Blackwater Park"
    assert result[0]["skippedCount"] == 2
    assert result[0]["favorited"] is True
    assert result[0]["dateAdded"] == "2024-06-15T10:30:00Z"
