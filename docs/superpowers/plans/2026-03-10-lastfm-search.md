# Last.fm Canonical Name Lookup Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `fetch_filter_data` to use `artist.search` first so listener counts are accurate for lowercase/un-normalized artist names.

**Architecture:** Prepend a `artist.search` call (limit=1) to resolve the canonical name before the existing `artist.getInfo` + MusicBrainz flow. Fall back to the raw name if search returns nothing.

**Tech Stack:** Python 3, requests, Last.fm API, MusicBrainz API, pytest

---

## Chunk 1: Update fetch_filter_data and tests

### Task 1: Write failing tests for the new 3-call flow

**Files:**
- Modify: `tests/test_music_discovery.py`

- [ ] **Step 1: Write a failing test for canonical name resolution**

Add these tests after the existing `test_fetch_filter_data_*` block in `tests/test_music_discovery.py`:

```python
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
        calls.append(kwargs.get("params", {}).get("method") or "musicbrainz")
        return [search_resp, getinfo_resp, mb_resp][len(calls) - 1]

    with patch("requests.get", side_effect=fake_get):
        result = md.fetch_filter_data("the eagles", "fake_key")

    assert calls[0] == "artist.search"
    assert calls[1] == "artist.getInfo"
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
```

- [ ] **Step 2: Update existing tests that mock requests.get**

The existing tests for `fetch_filter_data` mock `requests.get` with a fixed number of calls. They now need to account for the new search call prepended to the sequence.

Update `test_fetch_filter_data_returns_listeners_and_debut` (currently mocks 2 calls) to mock 3:

```python
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
```

Update `test_fetch_filter_data_missing_mbid` (currently mocks 1 call) to mock 2:

```python
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
```

Update `test_fetch_filter_data_lastfm_failure` — search call now happens first; test the case where search succeeds but getInfo fails:

```python
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
```

Update `test_fetch_filter_data_year_only_begin` to add search mock:

```python
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
```

`test_fetch_filter_data_network_error` needs no change — the exception fires on the first call (search) and returns `{}` as before.

- [ ] **Step 3: Run new tests to confirm they fail**

```bash
cd "/Users/brianhill/Scripts/Music Discovery"
python3 -m pytest tests/test_music_discovery.py -k "fetch_filter" -v
```

Expected: several FAIL or ERROR (new tests reference updated behavior not yet implemented)

---

### Task 2: Implement the updated fetch_filter_data

**Files:**
- Modify: `music_discovery.py` — `fetch_filter_data` function (lines 217–251)

- [ ] **Step 4: Replace fetch_filter_data with the new implementation**

```python
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
    except Exception:
        return {}
```

- [ ] **Step 5: Run all tests**

```bash
python3 -m pytest tests/test_music_discovery.py -v
```

Expected: all 51 tests pass

- [ ] **Step 6: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: use artist.search to resolve canonical name before getInfo"
```

---

### Task 3: Clear stale filter cache

**Files:**
- Delete: `~/.cache/music_discovery/filter_cache.json`

- [ ] **Step 7: Delete the filter cache**

```bash
rm ~/.cache/music_discovery/filter_cache.json
```

This file is outside the repo and has no git commit — just run the command before the next `python3 music_discovery.py` run. The next run will re-fetch all ~4500 candidates using the corrected lookup.
