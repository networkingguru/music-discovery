"""Tests for compare_similarity.py — Apple Music API POC."""

import json
import pathlib
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

# Generate a valid EC P-256 key for tests
_ec_key = ec.generate_private_key(ec.SECP256R1())
FAKE_P8_KEY = _ec_key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()

import sys, os
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from compare_similarity import (
    generate_apple_music_token,
    AppleMusicClient,
    compare_for_artist,
)


# ── JWT generation ──────────────────────────────────────────────────────────


class TestGenerateToken:
    def test_missing_credentials_raises(self, tmp_path):
        key_file = tmp_path / "key.p8"
        key_file.write_text(FAKE_P8_KEY)
        with pytest.raises(ValueError, match="APPLE_MUSIC_KEY_ID"):
            generate_apple_music_token("", "", str(key_file))

    def test_missing_key_file_raises(self):
        with pytest.raises(FileNotFoundError, match="private key not found"):
            generate_apple_music_token("KEY123", "TEAM456", "/nonexistent/key.p8")

    def test_successful_signing(self, tmp_path):
        key_file = tmp_path / "AuthKey.p8"
        key_file.write_text(FAKE_P8_KEY)
        token = generate_apple_music_token("KEY123", "TEAM456", str(key_file))
        assert isinstance(token, str)
        parts = token.split(".")
        assert len(parts) == 3, "JWT should have 3 dot-separated parts"


# ── AppleMusicClient ───────────────────────────────────────────────────────


class TestAppleMusicClient:
    @pytest.fixture
    def client(self):
        return AppleMusicClient("fake-token")

    def test_search_exact_match(self, client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": {
                "artists": {
                    "data": [
                        {"id": "111", "attributes": {"name": "Radiohead"}},
                        {"id": "222", "attributes": {"name": "Radiohead Tribute"}},
                    ]
                }
            }
        }
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client.session, "get", return_value=mock_resp):
            aid, name = client.search_artist("radiohead")
        assert aid == "111"
        assert name == "Radiohead"

    def test_search_no_results(self, client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": {"artists": {"data": []}}}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client.session, "get", return_value=mock_resp):
            aid, name = client.search_artist("xyznonexistent")
        assert aid is None
        assert name is None

    def test_search_api_error(self, client):
        import requests as req
        with patch.object(client.session, "get", side_effect=req.ConnectionError("timeout")):
            aid, name = client.search_artist("radiohead")
        assert aid is None
        assert name is None

    def test_similar_artists_success(self, client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [{
                "views": {
                    "similar-artists": {
                        "data": [
                            {"id": "A1", "attributes": {"name": "Thom Yorke"}},
                            {"id": "A2", "attributes": {"name": "Atoms for Peace"}},
                        ]
                    }
                }
            }]
        }
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client.session, "get", return_value=mock_resp):
            results = client.get_similar_artists("111")
        assert len(results) == 2
        assert results[0]["name"] == "Thom Yorke"

    def test_similar_artists_empty(self, client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [{"views": {}}]}
        mock_resp.raise_for_status = MagicMock()
        with patch.object(client.session, "get", return_value=mock_resp):
            results = client.get_similar_artists("111")
        assert results == []


# ── Comparison logic ───────────────────────────────────────────────────────


class TestCompareForArtist:
    @patch("compare_similarity.time.sleep")
    @patch("compare_similarity.scrape_musicmap_requests")
    def test_overlap_detection(self, mock_musicmap, mock_sleep):
        mock_musicmap.return_value = {
            "thom yorke": 0.9,
            "portishead": 0.7,
            "massive attack": 0.6,
        }
        apple_client = MagicMock()
        apple_client.search_artist.return_value = ("111", "Radiohead")
        apple_client.get_similar_artists.return_value = [
            {"name": "Thom Yorke", "id": "A1"},
            {"name": "Muse", "id": "A2"},
        ]
        result = compare_for_artist("radiohead", apple_client)
        assert "thom yorke" in result["overlap"]
        assert "muse" in result["apple_only"]
        assert "portishead" in result["musicmap_only"]
        assert "massive attack" in result["musicmap_only"]

    @patch("compare_similarity.time.sleep")
    @patch("compare_similarity.scrape_musicmap_requests")
    def test_apple_not_found_fallback(self, mock_musicmap, mock_sleep):
        mock_musicmap.return_value = {"artist a": 0.8, "artist b": 0.5}
        apple_client = MagicMock()
        apple_client.search_artist.return_value = (None, None)
        result = compare_for_artist("unknownartist", apple_client)
        assert result["apple_id"] is None
        assert result["apple_similar"] == []
        assert sorted(result["musicmap_only"]) == ["artist a", "artist b"]
