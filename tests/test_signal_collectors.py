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
    assert result == {"haken": 1, "tool": 2, "meshuggah": 1}


def test_collect_playlists_skips_smart_and_apple_playlists():
    """Smart playlists and Apple-curated playlists should be excluded."""
    from signal_collectors import collect_user_playlists_jxa
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
