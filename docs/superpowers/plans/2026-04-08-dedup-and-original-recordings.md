# Dedup Hardening + Original Studio Recordings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent duplicate tracks in the playlist and prefer original studio recordings over compilations/live/remixes.

**Architecture:** Two independent changes: (1) Add failsafe dedup gates and diagnostic logging to the build loop in `adaptive_engine.py`, (2) Add `_is_original_recording()` filter to `search_itunes()` and `fetch_artist_catalog()` in `music_discovery.py`.

**Tech Stack:** Python 3, regex, iTunes Search API, pytest

**Task Dependencies:**
- Task 2 requires Task 1 (`_is_original_recording()`)
- Task 3 requires Task 1
- Task 5 requires Task 4 (Task 5 replaces lines that Task 4 modifies — anchor by content not line numbers)
- Tasks 1-3 (`music_discovery.py`) are independent of Tasks 4-5 (`adaptive_engine.py`)

---

### Task 1: Add `_is_original_recording()` helper with tests

**Files:**
- Modify: `music_discovery.py:1073` (insert before `search_itunes`)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_music_discovery.py`:

```python
class TestIsOriginalRecording:
    """Unit tests for _is_original_recording() iTunes result filter."""

    def _make_result(self, track_name="Eye in the Sky", collection_name="Eye In the Sky",
                     artist_name="The Alan Parsons Project", track_count=10,
                     collection_artist_name=None):
        """Build a minimal iTunes API result dict."""
        d = {
            "trackName": track_name,
            "collectionName": collection_name,
            "artistName": artist_name,
            "trackCount": track_count,
        }
        if collection_artist_name is not None:
            d["collectionArtistName"] = collection_artist_name
        return d

    def test_original_studio_album(self):
        assert md._is_original_recording(self._make_result()) is True

    def test_va_compilation(self):
        r = self._make_result(collection_artist_name="Various Artists",
                              collection_name="80s 100 Hits", track_count=100)
        assert md._is_original_recording(r) is False

    def test_va_different_collection_artist(self):
        """collectionArtistName differs from artistName — VA/DJ compilation."""
        r = self._make_result(collection_artist_name="Y.O.G.A.",
                              collection_name="COW TECH MIX", track_count=15)
        assert md._is_original_recording(r) is False

    def test_dj_mix_collection_name(self):
        """DJ Mix keyword in collectionName catches DJ compilations."""
        r = self._make_result(collection_name="Ministry of Sound DJ Mix")
        assert md._is_original_recording(r) is False

    def test_greatest_hits_album(self):
        r = self._make_result(collection_name="Greatest Hits", track_count=16)
        assert md._is_original_recording(r) is False

    def test_best_of_album(self):
        r = self._make_result(collection_name="The Best of Journey", track_count=18)
        assert md._is_original_recording(r) is False

    def test_anthology_album(self):
        r = self._make_result(collection_name="Anthology", track_count=20)
        assert md._is_original_recording(r) is False

    def test_live_at_album(self):
        r = self._make_result(collection_name="Live at Madison Square Garden")
        assert md._is_original_recording(r) is False

    def test_live_from_album(self):
        r = self._make_result(collection_name="Live from Nowhere Near You")
        assert md._is_original_recording(r) is False

    def test_live_in_album(self):
        r = self._make_result(collection_name="Live in Houston 1981")
        assert md._is_original_recording(r) is False

    def test_unplugged_album(self):
        r = self._make_result(collection_name="MTV Unplugged in New York")
        assert md._is_original_recording(r) is False

    def test_now_thats_album(self):
        r = self._make_result(collection_name="Now That's What I Call Music 93",
                              track_count=40)
        assert md._is_original_recording(r) is False

    def test_n_hits_album(self):
        r = self._make_result(collection_name="100 Hits - Rock", track_count=100)
        assert md._is_original_recording(r) is False

    def test_live_track_name(self):
        r = self._make_result(track_name="Don't Stop Believin' (Live)")
        assert md._is_original_recording(r) is False

    def test_remix_track_name(self):
        r = self._make_result(track_name="Dreams (Gigamesh Edit) [Mixed]")
        assert md._is_original_recording(r) is False

    def test_acoustic_track_name(self):
        r = self._make_result(track_name="Creep (Acoustic)")
        assert md._is_original_recording(r) is False

    def test_demo_track_name(self):
        r = self._make_result(track_name="Creep [Demo]")
        assert md._is_original_recording(r) is False

    def test_radio_edit_track_name(self):
        r = self._make_result(track_name="Bohemian Rhapsody (Radio Edit)")
        assert md._is_original_recording(r) is False

    def test_re_recorded_track_name(self):
        r = self._make_result(track_name="Don't Stop Believin' (Re-Recorded)")
        assert md._is_original_recording(r) is False

    def test_instrumental_track_name(self):
        r = self._make_result(track_name="Creep (Instrumental)")
        assert md._is_original_recording(r) is False

    def test_karaoke_track_name(self):
        r = self._make_result(track_name="Creep (Karaoke)")
        assert md._is_original_recording(r) is False

    def test_single_edit_track_name(self):
        r = self._make_result(track_name="Stairway to Heaven (Single Edit)")
        assert md._is_original_recording(r) is False

    def test_club_mix_track_name(self):
        r = self._make_result(track_name="Blue Monday (Club Mix)")
        assert md._is_original_recording(r) is False

    def test_sessions_track_name(self):
        r = self._make_result(track_name="Dreams (Sessions, Roughs & Outtakes)")
        assert md._is_original_recording(r) is False

    def test_take_n_track_name(self):
        r = self._make_result(track_name="Dreams (Take 2)")
        assert md._is_original_recording(r) is False

    def test_take_nn_track_name(self):
        """Multi-digit take numbers must also be caught."""
        r = self._make_result(track_name="Dreams (Take 12)")
        assert md._is_original_recording(r) is False

    def test_bonus_track_name(self):
        r = self._make_result(track_name="Hidden Track (Bonus)")
        assert md._is_original_recording(r) is False

    def test_extended_track_name(self):
        r = self._make_result(track_name="Blue Monday (Extended)")
        assert md._is_original_recording(r) is False

    # --- ALLOWED cases (should return True) ---

    def test_remastered_is_allowed(self):
        """Remastered is a fidelity change, not a different performance."""
        r = self._make_result(track_name="Don't Stop Believin' (Remastered 2022)",
                              collection_name="Escape (2022 Remaster)")
        assert md._is_original_recording(r) is True

    def test_double_album_allowed(self):
        r = self._make_result(track_name="Comfortably Numb",
                              collection_name="The Wall", track_count=26)
        assert md._is_original_recording(r) is True

    def test_missing_collection_artist_key(self):
        """No collectionArtistName key at all — should not raise."""
        r = {"trackName": "Dreams", "collectionName": "Rumours",
             "artistName": "Fleetwood Mac", "trackCount": 11}
        assert md._is_original_recording(r) is True

    def test_high_track_count_compilation(self):
        r = self._make_result(track_count=40)
        assert md._is_original_recording(r) is False

    def test_track_count_35_allowed(self):
        """Boundary: 35 is allowed, 36 is not."""
        r = self._make_result(track_count=35)
        assert md._is_original_recording(r) is True

    def test_track_count_36_rejected(self):
        r = self._make_result(track_count=36)
        assert md._is_original_recording(r) is False

    def test_live_and_let_die_not_rejected(self):
        """'Live' in the track title (not in parens) must not trigger the filter."""
        r = self._make_result(track_name="Live and Let Die",
                              collection_name="Band on the Run")
        assert md._is_original_recording(r) is True

    def test_collection_artist_matches_artist(self):
        """collectionArtistName present but same as artistName — not a VA compilation."""
        r = self._make_result(collection_artist_name="The Alan Parsons Project")
        assert md._is_original_recording(r) is True

    def test_essential_tremors_not_rejected(self):
        """'Essential' was excluded from keywords to avoid this false positive."""
        r = self._make_result(collection_name="Essential Tremors",
                              artist_name="Drive-By Truckers")
        assert md._is_original_recording(r) is True

    def test_collection_name_none_does_not_crash(self):
        """collectionName=null from API must not raise TypeError."""
        r = {"trackName": "Eye in the Sky", "collectionName": None,
             "artistName": "The Alan Parsons Project", "trackCount": 10}
        assert md._is_original_recording(r) is True

    def test_track_name_none_does_not_crash(self):
        """trackName=null from API must not raise TypeError."""
        r = {"trackName": None, "collectionName": "Eye In the Sky",
             "artistName": "The Alan Parsons Project", "trackCount": 10}
        assert md._is_original_recording(r) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::TestIsOriginalRecording -v 2>&1 | head -30`
Expected: FAIL — `AttributeError: module 'music_discovery' has no attribute '_is_original_recording'`

- [ ] **Step 3: Implement `_is_original_recording()`**

Add to `music_discovery.py` before `search_itunes()` (around line 1073):

```python
# Regex: track name contains a parenthetical/bracket variant suffix
_VARIANT_TRACK_RE = re.compile(
    r"[\(\[](Live|Remix|Re-Recorded|Acoustic|Demo|Radio Edit|"
    r"Instrumental|Karaoke|Single Edit|Club Mix|"
    r"Extended|Sessions|Outtakes|Take \d+|Mixed|Bonus)",
    re.IGNORECASE,
)

# Regex: collection name matches compilation keywords (word-boundary anchored)
_COMPILATION_ALBUM_RE = re.compile(
    r"\b(Greatest\s+Hits|Best\s+of|Anthology|Classics|"
    r"\d+\s+Hits|DJ\s+Mix|Lullaby|Renditions|"
    r"Live\s+at|Live\s+from|Live\s+in|Live\s+Tour|"
    r"Unplugged|MTV|Now\s+That'?s)\b",
    re.IGNORECASE,
)


def _is_original_recording(result: dict) -> bool:
    """Return False if an iTunes result is likely a non-original recording.

    Checks: VA compilation, track-name variant suffixes, compilation album
    name keywords, and high track count. Handles missing keys gracefully.
    Remastered/Stereo Mix/Mono are ALLOWED (fidelity changes, not different
    performances)."""
    # 1. VA compilation: collectionArtistName differs from artistName
    collection_artist = result.get("collectionArtistName", "")
    if collection_artist:
        artist = result.get("artistName", "")
        if collection_artist.lower().strip() != artist.lower().strip():
            return False

    # 2. Track name variant suffix
    track_name = result.get("trackName") or ""
    if _VARIANT_TRACK_RE.search(track_name):
        return False

    # 3. Compilation album name keywords
    collection_name = result.get("collectionName") or ""
    if _COMPILATION_ALBUM_RE.search(collection_name):
        return False

    # 4. High track count (>35 = almost certainly a compilation)
    track_count = result.get("trackCount", 0) or 0
    if track_count > 35:
        return False

    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::TestIsOriginalRecording -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: add _is_original_recording() filter for iTunes results (#14)"
```

---

### Task 2: Update `search_itunes()` to prefer originals

**Files:**
- Modify: `music_discovery.py:1075-1112` (`search_itunes` function)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_music_discovery.py`:

```python
class TestSearchItunesOriginalPreference:
    """Verify search_itunes prefers original recordings over compilations."""

    def _fake_response(self, results):
        """Build a mock requests.Response-like object."""
        import types
        resp = types.SimpleNamespace()
        resp.status_code = 200
        resp.json = lambda: {"results": results}
        return resp

    def _song(self, track_id, artist, track, collection="Album",
              duration_ms=240000, collection_artist=None, track_count=10):
        d = {
            "kind": "song",
            "trackId": track_id,
            "artistName": artist,
            "trackName": track,
            "collectionName": collection,
            "trackTimeMillis": duration_ms,
            "trackCount": track_count,
        }
        if collection_artist is not None:
            d["collectionArtistName"] = collection_artist
        return d

    def test_prefers_original_over_compilation(self, monkeypatch):
        compilation = self._song(1, "Journey", "Don't Stop Believin'",
                                 collection="Greatest Hits", track_count=16)
        original = self._song(2, "Journey", "Don't Stop Believin'",
                              collection="Escape")
        # Compilation comes first in API response
        monkeypatch.setattr("music_discovery.requests.get",
                            lambda *a, **kw: self._fake_response([compilation, original]))
        result = md.search_itunes("Journey", "Don't Stop Believin'")
        assert result.store_id == "2"

    def test_falls_back_to_compilation_when_no_original(self, monkeypatch):
        compilation = self._song(1, "Journey", "Don't Stop Believin'",
                                 collection="Greatest Hits", track_count=16)
        monkeypatch.setattr("music_discovery.requests.get",
                            lambda *a, **kw: self._fake_response([compilation]))
        result = md.search_itunes("Journey", "Don't Stop Believin'")
        assert result.store_id == "1"

    def test_prefers_exact_artist_original_over_fuzzy_original(self, monkeypatch):
        fuzzy = self._song(1, "The Alan Parsons Project", "Eye in the Sky",
                           collection="Eye In the Sky")
        exact = self._song(2, "Alan Parsons Project", "Eye in the Sky",
                           collection="Eye In the Sky")
        monkeypatch.setattr("music_discovery.requests.get",
                            lambda *a, **kw: self._fake_response([fuzzy, exact]))
        result = md.search_itunes("Alan Parsons Project", "Eye in the Sky")
        assert result.store_id == "2"

    def test_prefers_original_fuzzy_over_compilation_exact(self, monkeypatch):
        """Original with fuzzy match beats compilation with exact match."""
        comp_exact = self._song(1, "Journey", "Don't Stop Believin'",
                                collection="Greatest Hits", track_count=16)
        orig_fuzzy = self._song(2, "Journey & Friends", "Don't Stop Believin'",
                                collection="Escape")
        monkeypatch.setattr("music_discovery.requests.get",
                            lambda *a, **kw: self._fake_response([comp_exact, orig_fuzzy]))
        # Artist is "Journey" — "Journey & Friends" is fuzzy match
        result = md.search_itunes("Journey", "Don't Stop Believin'")
        # Original fuzzy (priority 2) beats compilation exact (priority 3)
        assert result.store_id == "2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::TestSearchItunesOriginalPreference -v 2>&1 | head -20`
Expected: FAIL — `test_prefers_original_over_compilation` fails (returns store_id "1")

- [ ] **Step 3: Rewrite `search_itunes()` with original preference**

Replace the body of `search_itunes()` in `music_discovery.py` (lines 1075-1112):

```python
def search_itunes(artist, track_name):
    """Search the iTunes/Apple Music catalog for a track.
    Returns a SearchResult. Use bool() to check if a track was found.
    Verifies the artist name matches to avoid returning wrong tracks.
    Prefers original studio recordings over compilations/live/remixes.
    Free API — no key required."""
    try:
        resp = requests.get(ITUNES_SEARCH_URL, timeout=10, params={
            "term":  f"{artist} {track_name}",
            "media": "music",
            "limit": 10,
        })
        if resp.status_code != 200:
            return SearchResult(None, searched_ok=False)
        results = resp.json().get("results", [])
        results = [r for r in results if r.get("kind") == "song"]
        artist_lower = artist.strip().lower()

        # Partition into original and fallback (compilation/live/remix)
        originals = [r for r in results if _is_original_recording(r)]
        fallbacks = [r for r in results if not _is_original_recording(r)]

        # Search order: original exact, original fuzzy, fallback exact, fallback fuzzy
        for pool in (originals, fallbacks):
            # Exact artist match
            for r in pool:
                duration_ms = r.get("trackTimeMillis", 0)
                if duration_ms < 90_000 or duration_ms > 600_000:
                    continue
                result_artist = r.get("artistName", "").strip().lower()
                if result_artist == artist_lower:
                    return SearchResult(str(r["trackId"]), True,
                                        r.get("artistName", ""), r.get("trackName", ""))
            # Fuzzy artist match
            for r in pool:
                duration_ms = r.get("trackTimeMillis", 0)
                if duration_ms < 90_000 or duration_ms > 600_000:
                    continue
                result_artist = r.get("artistName", "").strip().lower()
                if artist_lower in result_artist or result_artist in artist_lower:
                    return SearchResult(str(r["trackId"]), True,
                                        r.get("artistName", ""), r.get("trackName", ""))
        return SearchResult(None, searched_ok=True)
    except Exception as e:
        log.debug(f"search_itunes failed for '{artist} - {track_name}': {e}")
        return SearchResult(None, searched_ok=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::TestSearchItunesOriginalPreference tests/test_music_discovery.py::TestIsOriginalRecording -v`
Expected: All tests PASS

- [ ] **Step 5: Run the full existing test suite for regressions**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: search_itunes() prefers original studio recordings (#14)"
```

---

### Task 3: Update `fetch_artist_catalog()` with filtering and soft fallback

**Files:**
- Modify: `music_discovery.py:1115-1152` (`fetch_artist_catalog` function)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_music_discovery.py`:

```python
class TestFetchArtistCatalogOriginalPreference:
    """Verify fetch_artist_catalog filters non-originals with soft fallback."""

    def _fake_response(self, results):
        import types
        resp = types.SimpleNamespace()
        resp.status_code = 200
        resp.json = lambda: {"results": results}
        return resp

    def _song(self, artist, track, collection="Album",
              duration_ms=240000, collection_artist=None, track_count=10):
        return {
            "kind": "song",
            "artistName": artist,
            "trackName": track,
            "collectionName": collection,
            "trackTimeMillis": duration_ms,
            "trackCount": track_count,
            **({"collectionArtistName": collection_artist} if collection_artist else {}),
        }

    def test_filters_compilation_tracks(self, monkeypatch):
        songs = [
            self._song("Journey", "Don't Stop Believin'", collection="Escape"),
            self._song("Journey", "Faithfully", collection="Greatest Hits"),
            self._song("Journey", "Open Arms", collection="Frontiers"),
        ]
        monkeypatch.setattr("music_discovery.requests.get",
                            lambda *a, **kw: self._fake_response(songs))
        tracks = md.fetch_artist_catalog("Journey")
        names = [t["name"] for t in tracks]
        assert "Don't Stop Believin'" in names
        assert "Open Arms" in names
        assert "Faithfully" not in names

    def test_soft_fallback_when_all_filtered(self, monkeypatch):
        """If all tracks are non-original, return them anyway (soft fallback)."""
        songs = [
            self._song("Journey", "Don't Stop Believin'", collection="Greatest Hits"),
            self._song("Journey", "Faithfully", collection="Greatest Hits"),
        ]
        monkeypatch.setattr("music_discovery.requests.get",
                            lambda *a, **kw: self._fake_response(songs))
        tracks = md.fetch_artist_catalog("Journey")
        assert len(tracks) == 2  # Fallback: all returned despite being compilations

    def test_filter_before_dedup_preserves_originals(self, monkeypatch):
        """Compilation version arrives first, original second. Original must survive."""
        songs = [
            self._song("Journey", "Don't Stop Believin'", collection="Greatest Hits"),
            self._song("Journey", "Don't Stop Believin'", collection="Escape"),
        ]
        monkeypatch.setattr("music_discovery.requests.get",
                            lambda *a, **kw: self._fake_response(songs))
        tracks = md.fetch_artist_catalog("Journey")
        names = [t["name"] for t in tracks]
        assert "Don't Stop Believin'" in names
        assert len(tracks) == 1  # Deduplicated to one copy
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::TestFetchArtistCatalogOriginalPreference -v 2>&1 | head -20`
Expected: FAIL — `test_filters_compilation_tracks` fails ("Faithfully" still in results)

- [ ] **Step 3: Rewrite `fetch_artist_catalog()` with filter-before-dedup and soft fallback**

Replace the body of `fetch_artist_catalog()` in `music_discovery.py` (lines 1115-1152):

```python
def fetch_artist_catalog(artist):
    """Fetch all available songs for an artist from the iTunes Search API.
    Returns list of {"name": str, "artist": str}. Deduplicates by track name.
    Prefers original studio recordings; falls back to unfiltered if all are
    filtered out.  Free API — no key required."""
    try:
        resp = requests.get(ITUNES_SEARCH_URL, timeout=15, params={
            "term":  artist,
            "media": "music",
            "entity": "song",
            "limit": 200,
        })
        if resp.status_code != 200:
            return []
        results = resp.json().get("results", [])
        artist_lower = artist.strip().lower()

        # First pass: collect originals only (filter before dedup)
        seen = set()
        tracks = []
        for r in results:
            if r.get("kind") != "song":
                continue
            result_artist = r.get("artistName", "").strip().lower()
            if result_artist != artist_lower and not (
                artist_lower in result_artist or result_artist in artist_lower
            ):
                continue
            duration_ms = r.get("trackTimeMillis", 0)
            if duration_ms < 90_000 or duration_ms > 600_000:
                continue
            if not _is_original_recording(r):
                continue
            track_name = r.get("trackName", "")
            key = track_name.lower()
            if key in seen:
                continue
            seen.add(key)
            tracks.append({"name": track_name, "artist": r.get("artistName", "")})

        # Soft fallback: if filtering removed everything, return unfiltered
        if not tracks:
            seen = set()
            for r in results:
                if r.get("kind") != "song":
                    continue
                result_artist = r.get("artistName", "").strip().lower()
                if result_artist != artist_lower and not (
                    artist_lower in result_artist or result_artist in artist_lower
                ):
                    continue
                duration_ms = r.get("trackTimeMillis", 0)
                if duration_ms < 90_000 or duration_ms > 600_000:
                    continue
                track_name = r.get("trackName", "")
                key = track_name.lower()
                if key in seen:
                    continue
                seen.add(key)
                tracks.append({"name": track_name, "artist": r.get("artistName", "")})
        return tracks
    except Exception as e:
        log.debug(f"fetch_artist_catalog failed for '{artist}': {e}")
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::TestFetchArtistCatalogOriginalPreference tests/test_music_discovery.py::TestIsOriginalRecording -v`
Expected: All tests PASS

- [ ] **Step 5: Run the full existing test suite for regressions**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: fetch_artist_catalog() filters non-originals with soft fallback (#14)"
```

---

### Task 4: Add debug logging to the build loop

**Files:**
- Modify: `adaptive_engine.py:49-67` (`_load_offered_tracks`)
- Modify: `adaptive_engine.py:1105-1231` (build loop)

- [ ] **Step 1: Add entry count log to `_load_offered_tracks`**

In `adaptive_engine.py`, modify `_load_offered_tracks()` (line 49-67). Add a log line after building the set:

```python
def _load_offered_tracks(path: pathlib.Path) -> tuple[set, list]:
    """Load previously offered tracks. Returns (set of (artist, track), raw entries list).

    Adds both raw and normalized keys to the set so cross-round dedup catches
    formatting variants (e.g. 'Weird Fishes / Arpeggi' vs 'Weird Fishes/Arpeggi')."""
    if not path.exists():
        return set(), []
    try:
        from signal_experiment import _normalize_for_match
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get("tracks", [])
        track_set = set()
        for t in entries:
            track_set.add((t["artist"], t["track"]))
            track_set.add((t["artist"], _normalize_for_match(t["track"])))
        # Issue #13 diagnostic: verify cross-round state loaded correctly
        log.debug("  _load_offered_tracks: %d entries -> %d set keys from %s",
                  len(entries), len(track_set), path)
        return track_set, entries
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log.warning("Corrupt offered_tracks.json, starting fresh: %s", e)
        return set(), []
```

- [ ] **Step 2: Add per-artist and per-track diagnostic logging to the build loop**

In `adaptive_engine.py`, add logging to the build loop. After `all_tracks` is built (after line 1145):

```python
        all_tracks = lastfm_tracks + unique_catalog
        # Issue #13 diagnostic: log full track list to detect Last.fm dupes or variants
        log.debug("  [%s] all_tracks (%d): %s",
                  artist, len(all_tracks),
                  [t.get("name", "?") for t in all_tracks])
```

After the dedup check passes (after the `if key in offered_set ... continue` block, i.e., when the condition was False and execution falls through), add:

```python
            # Issue #13 diagnostic: log WHY this track passed the dedup check
            # Guard with isEnabledFor to avoid O(n) comprehension over offered_set
            # when DEBUG is disabled
            if log.isEnabledFor(logging.DEBUG):
                artist_entries_in_set = [
                    entry for entry in offered_set if entry[0] == artist.lower()
                ]
                log.debug("    DEDUP PASS: key=%s in_set=%s | norm=%s in_set=%s | "
                          "artist_entries=%d: %s",
                          key, key in offered_set, norm_key, norm_key in offered_set,
                          len(artist_entries_in_set), artist_entries_in_set[:10])
```

After the post-resolution dedup check passes (after line 1188 `continue`), add:

```python
            # Issue #13 diagnostic: log post-resolution pass
            if log.isEnabledFor(logging.DEBUG):
                canon_artist_entries = [
                    entry for entry in offered_set if entry[0] == canon_artist
                ]
                log.debug("    POST-RES PASS: canon_key=%s in_set=%s | canon_norm=%s "
                          "in_set=%s | canon_artist_entries=%d: %s",
                          canon_key, canon_key in offered_set,
                          canon_norm, canon_norm in offered_set,
                          len(canon_artist_entries), canon_artist_entries[:10])
```

After a successful add (after line 1212, inside the `if add_result:` block), add:

```python
                # Issue #13 diagnostic: log all 6 keys added + actual resolution
                log.debug("    ADDED: actual=(%s, %s) | keys added: %s",
                          actual_artist, actual_track,
                          [key, norm_key, actual_key, actual_norm,
                           canon_key, canon_norm])
```

- [ ] **Step 3: Verify logging works by running a quick check**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -c "import adaptive_engine; print('import OK')"` 
Expected: `import OK` (no syntax errors)

- [ ] **Step 4: Run existing tests for regressions**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_adaptive_engine.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add adaptive_engine.py
git commit -m "diag: add debug logging to build loop dedup path (#13)"
```

---

### Task 5: Add failsafe dedup with expanded `offered_tracks`

**Files:**
- Modify: `adaptive_engine.py:1190-1212` (failsafe gates)
- Modify: `adaptive_engine.py:1200` (expand `offered_tracks` to store all 6 variants)
- Test: `tests/test_adaptive_engine.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_adaptive_engine.py`. First, add the import at the top of the file alongside existing imports:

```python
from signal_experiment import _normalize_for_match
```

Then add the test class:

```python
class TestFailsafeDedup:
    """Verify the failsafe dedup gate key coverage.

    These tests verify that the expanded offered_tracks set (with all 6 key
    variants per track) correctly catches duplicates that arrive with different
    artist name forms — the exact scenario that caused issue #13.
    The tests validate the KEY DESIGN: that canon_key from a second attempt
    matches an entry added by a first attempt with a different ranked artist name."""

    def test_canonical_key_catches_the_prefix_mismatch(self):
        """Core #13 scenario: ranked artist 'alan parsons project' adds track,
        then same track arrives via 'the alan parsons project'. The expanded
        offered_tracks must catch this via canon_key/actual_key overlap."""
        offered_tracks = set()

        # First add: ranked artist = "alan parsons project" (no "the")
        key1 = ("alan parsons project", "eye in the sky")
        norm1 = ("alan parsons project", _normalize_for_match("Eye in the Sky"))
        actual1 = ("the alan parsons project", "eye in the sky")  # Music.app name
        actual_norm1 = ("the alan parsons project", _normalize_for_match("Eye in the Sky"))
        canon1 = ("the alan parsons project", "eye in the sky")  # iTunes canonical
        canon_norm1 = ("the alan parsons project", _normalize_for_match("Eye in the Sky"))
        for k in (key1, norm1, actual1, actual_norm1, canon1, canon_norm1):
            offered_tracks.add(k)

        # Second attempt with different ranked artist but same canonical resolution
        second_canon_key = ("the alan parsons project", "eye in the sky")
        second_canon_norm = ("the alan parsons project", _normalize_for_match("Eye in the Sky"))
        assert second_canon_key in offered_tracks, \
            "Pre-add failsafe must catch canonical duplicate via 'the' prefix"
        assert second_canon_norm in offered_tracks

    def test_six_variants_cover_all_name_forms(self):
        """Verify all 6 key forms are present after one track add."""
        offered_tracks = set()
        variants = [
            ("foo", "bar"),
            ("foo", _normalize_for_match("Bar")),
            ("the foo", "bar"),
            ("the foo", _normalize_for_match("Bar")),
            ("the foo", "bar"),
            ("the foo", _normalize_for_match("Bar")),
        ]
        for v in variants:
            offered_tracks.add(v)

        # Any of these forms should be caught
        assert ("foo", "bar") in offered_tracks
        assert ("the foo", "bar") in offered_tracks
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_adaptive_engine.py::TestFailsafeDedup -v`
Expected: PASS (these validate the key design that the failsafe relies on)

- [ ] **Step 3: Implement the failsafe dedup and expanded `offered_tracks`**

In `adaptive_engine.py`, modify the build loop. **Important: Task 4 shifts line numbers. Anchor by content, not line numbers.** Find the block starting with `# Try to add to playlist` and the `_add_track_to_named_playlist` call, through `added_count += 1`. Replace that entire block (including the Task 4 `ADDED` log line which is already incorporated below):

```python
            # Pre-add failsafe: check offered_tracks (per-round) for canonical match
            # This catches duplicates that somehow passed offered_set checks (#13)
            if canon_key in offered_tracks or canon_norm in offered_tracks:
                if log.isEnabledFor(logging.DEBUG):
                    matching = [e for e in offered_tracks
                                if e[0] in (canon_artist, artist.lower())]
                else:
                    matching = []
                log.warning("  FAILSAFE PRE-ADD: duplicate caught for %s — %s "
                            "(canon_key=%s, canon_norm=%s). "
                            "Matching entries in offered_tracks: %s",
                            canon_artist, canon_track, canon_key, canon_norm,
                            matching[:10])
                continue

            # Try to add to playlist
            add_result = _add_track_to_named_playlist(
                artist, track_name, playlist_name, search_result=result)
            if add_result:
                # Use actual names from the track that was added (may differ
                # from Last.fm names due to API resolution)
                actual_artist, actual_track = add_result
                actual_key = (actual_artist.lower(), actual_track.lower())
                actual_norm = (actual_artist.lower(),
                               _normalize_for_match(actual_track))

                # Post-add failsafe: if actual resolution matches something
                # already added this round, skip the bookkeeping (playlist add
                # already happened — this only protects offered_entries integrity).
                # Still increment added_count since the track IS in the playlist.
                if actual_key in offered_tracks or actual_norm in offered_tracks:
                    log.warning("  FAILSAFE POST-ADD: duplicate actual resolution "
                                "for %s — %s (already in offered_tracks). "
                                "Playlist add happened but skipping bookkeeping.",
                                actual_artist, actual_track)
                    added_count += 1
                else:
                    # Expand offered_tracks with all 6 key variants (#13)
                    offered_tracks.add(key)
                    offered_tracks.add(norm_key)
                    offered_tracks.add(actual_key)
                    offered_tracks.add(actual_norm)
                    offered_tracks.add(canon_key)
                    offered_tracks.add(canon_norm)
                    offered_set.add(key)
                    offered_set.add(norm_key)
                    offered_set.add(actual_key)
                    offered_set.add(actual_norm)
                    offered_set.add(canon_key)
                    offered_set.add(canon_norm)
                    offered_entries.append({
                        "artist": actual_artist.lower(),
                        "track": actual_track.lower(),
                        "round": current_round,
                    })
                    # Issue #13 diagnostic: log all 6 keys added + actual resolution
                    log.debug("    ADDED: actual=(%s, %s) | keys added: %s",
                              actual_artist, actual_track,
                              [key, norm_key, actual_key, actual_norm,
                               canon_key, canon_norm])
                    added_count += 1
```

- [ ] **Step 4: Run tests to verify nothing broke**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_adaptive_engine.py -v`
Expected: All tests PASS

- [ ] **Step 5: Verify no syntax errors**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -c "import adaptive_engine; print('import OK')"`
Expected: `import OK`

- [ ] **Step 6: Commit**

```bash
git add adaptive_engine.py tests/test_adaptive_engine.py
git commit -m "fix: failsafe dedup with expanded offered_tracks (#13)"
```

---

### Task 6: Integration verification with live iTunes API

**Files:** None modified — read-only verification

- [ ] **Step 1: Test `_is_original_recording()` against live API data**

Run a quick script to verify filtering works with real API responses:

```bash
cd "/Users/brianhill/Scripts/Music Discovery" && python3 -c "
import requests, json
from music_discovery import _is_original_recording

for query in ['alan parsons project eye in the sky',
              'journey dont stop believin',
              'fleetwood mac dreams']:
    resp = requests.get('https://itunes.apple.com/search',
                        params={'term': query, 'media': 'music', 'limit': 10})
    results = [r for r in resp.json()['results'] if r.get('kind') == 'song']
    print(f'\n=== {query} ===')
    for r in results:
        ok = _is_original_recording(r)
        tag = 'ORIG' if ok else 'SKIP'
        print(f'  [{tag}] {r[\"trackName\"]} | {r[\"collectionName\"]} | '
              f'tracks={r.get(\"trackCount\",\"?\")} | '
              f'coll_artist={r.get(\"collectionArtistName\", \"(none)\")}')
"
```

Expected: Original studio album versions tagged `ORIG`, compilations/live/remixes tagged `SKIP`. At least one `ORIG` per query.

- [ ] **Step 2: Test `search_itunes()` returns original versions**

```bash
cd "/Users/brianhill/Scripts/Music Discovery" && python3 -c "
from music_discovery import search_itunes
for artist, track in [('The Alan Parsons Project', 'Eye in the Sky'),
                      ('Journey', 'Dont Stop Believin'),
                      ('Fleetwood Mac', 'Dreams')]:
    r = search_itunes(artist, track)
    print(f'{artist} — {track}: store_id={r.store_id}, '
          f'canon={r.canonical_artist} — {r.canonical_track}')
"
```

Expected: All three return valid SearchResults with original album versions.

- [ ] **Step 3: Test `fetch_artist_catalog()` filtering**

```bash
cd "/Users/brianhill/Scripts/Music Discovery" && python3 -c "
from music_discovery import fetch_artist_catalog
tracks = fetch_artist_catalog('Journey')
print(f'Journey catalog: {len(tracks)} tracks (after filtering)')
for t in tracks[:10]:
    print(f'  {t[\"name\"]}')
"
```

Expected: Returns tracks, no "Greatest Hits" album tracks unless ALL tracks were compilations (soft fallback).

- [ ] **Step 4: Run the full test suite one final time**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/ -v --tb=short 2>&1 | tail -30`
Expected: All tests PASS

- [ ] **Step 5: Commit is not needed** — this task is read-only verification.
