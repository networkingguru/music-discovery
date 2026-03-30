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


def test_collect_ratings_averages_centered_by_artist():
    """Ratings should center on 3-star and average per artist."""
    from signal_collectors import collect_ratings_jxa
    fake_output = json.dumps([
        {"artist": "Haken", "rating": 100},   # 5-star -> +1.0
        {"artist": "Haken", "rating": 80},    # 4-star -> +0.5
        {"artist": "Tool", "rating": 40},     # 2-star -> -0.5
        {"artist": "tool", "rating": 20},     # 1-star -> -1.0
    ])
    with patch("signal_collectors._run_jxa", return_value=(fake_output, 0)):
        result = collect_ratings_jxa()
    assert "haken" in result
    assert abs(result["haken"]["avg_centered"] - 0.75) < 0.001
    assert result["haken"]["count"] == 2
    assert "tool" in result
    assert abs(result["tool"]["avg_centered"] - (-0.75)) < 0.001
    assert result["tool"]["count"] == 2


def test_collect_ratings_unrated_treated_as_neutral():
    """Unrated tracks (rating=0) should count as 3-star (centered=0.0)."""
    from signal_collectors import collect_ratings_jxa
    fake_output = json.dumps([
        {"artist": "Haken", "rating": 100},
        {"artist": "Haken", "rating": 0},
    ])
    with patch("signal_collectors._run_jxa", return_value=(fake_output, 0)):
        result = collect_ratings_jxa()
    assert abs(result["haken"]["avg_centered"] - 0.5) < 0.001
    assert result["haken"]["count"] == 2


def test_collect_ratings_skips_empty_artist():
    """Tracks with empty/missing artist should be skipped."""
    from signal_collectors import collect_ratings_jxa
    fake_output = json.dumps([
        {"artist": "", "rating": 100},
        {"artist": "Haken", "rating": 80},
    ])
    with patch("signal_collectors._run_jxa", return_value=(fake_output, 0)):
        result = collect_ratings_jxa()
    assert "" not in result
    assert "haken" in result


def test_collect_ratings_computed_rating_treated_as_neutral():
    """Computed/auto ratings (not multiples of 20) should be neutral."""
    from signal_collectors import collect_ratings_jxa
    fake_output = json.dumps([
        {"artist": "Haken", "rating": 100},   # 5-star -> +1.0
        {"artist": "Haken", "rating": 1},     # computed -> 0.0
    ])
    with patch("signal_collectors._run_jxa", return_value=(fake_output, 0)):
        result = collect_ratings_jxa()
    assert abs(result["haken"]["avg_centered"] - 0.5) < 0.001  # (1.0 + 0.0) / 2
    assert result["haken"]["count"] == 2


def test_collect_ratings_jxa_failure():
    """Should raise RuntimeError on JXA failure."""
    from signal_collectors import collect_ratings_jxa
    with patch("signal_collectors._run_jxa", return_value=("error", 1)):
        with pytest.raises(RuntimeError, match="JXA ratings read failed"):
            collect_ratings_jxa()


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
