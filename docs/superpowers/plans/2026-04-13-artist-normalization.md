# Artist Name Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix artist name normalization across the dedup, blocklist, cooldown, and scoring pipelines so that variant spellings (e.g., "mr. mister" vs "mr mister", "the cars" vs "cars") match correctly.

**Architecture:** Add a `_normalize_artist()` function to `adaptive_engine.py` and apply it at every artist-name comparison point. Add a non-artist term filter during candidate generation. Clean up false-positive blocklist/strike entries.

**Tech Stack:** Python 3, `re`, `unicodedata`, pytest

---

### Task 1: `_normalize_artist()` function + unit tests

**Files:**
- Modify: `adaptive_engine.py` (top of file, after imports)
- Modify: `tests/test_adaptive_engine.py` (new test class)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_adaptive_engine.py`:

```python
# At top, add to imports:
from adaptive_engine import _normalize_artist

# After the last test class:

class TestNormalizeArtist:
    """Unit tests for _normalize_artist() — artist name normalization."""

    # ── Basic normalization ──────────────────────────────────────────────────

    def test_the_prefix_stripped(self):
        assert _normalize_artist("the cars") == "cars"

    def test_the_prefix_case_insensitive(self):
        assert _normalize_artist("The Cars") == "cars"

    def test_ampersand_to_and(self):
        assert _normalize_artist("hall & oates") == "hall and oates"

    def test_ampersand_no_spaces(self):
        assert _normalize_artist("hall&oates") == "hall and oates"

    def test_ampersand_one_space(self):
        assert _normalize_artist("hall &oates") == "hall and oates"

    def test_period_stripped(self):
        assert _normalize_artist("mr. mister") == "mr mr"

    def test_plain_name_unchanged(self):
        assert _normalize_artist("radiohead") == "radiohead"

    def test_already_lowercase(self):
        assert _normalize_artist("iron maiden") == "iron maiden"

    # ── Unicode ──────────────────────────────────────────────────────────────

    def test_unicode_accent_stripped(self):
        assert _normalize_artist("terence trent d\u00b4arby") == "terence trent darby"

    def test_unicode_combining_accent(self):
        assert _normalize_artist("beyonc\u00e9") == "beyonce"

    # ── Abbreviation map ─────────────────────────────────────────────────────

    def test_mister_to_mr(self):
        assert _normalize_artist("mister mister") == "mr mr"

    def test_saint_to_st(self):
        assert _normalize_artist("saint etienne") == "st etienne"

    def test_mr_dot_mister_matches_mister_mister(self):
        """The headline bug: both variants must normalize identically."""
        assert _normalize_artist("mr. mister") == _normalize_artist("mister mister")

    # ── Edge cases ───────────────────────────────────────────────────────────

    def test_empty_string(self):
        assert _normalize_artist("") == ""

    def test_only_punctuation_fallback(self):
        """'!!!' (a real band) — normalization would produce '', so fallback to lowered original."""
        assert _normalize_artist("!!!") == "!!!"

    def test_the_the_preserved(self):
        """'The The' is a real band — length guard prevents stripping to just 'the' or ''."""
        assert _normalize_artist("the the") == "the the"

    def test_the_alone_preserved(self):
        assert _normalize_artist("the") == "the"

    # ── Punctuation-heavy names ──────────────────────────────────────────────

    def test_acdc(self):
        assert _normalize_artist("ac/dc") == "acdc"

    def test_mia(self):
        assert _normalize_artist("m.i.a.") == "mia"

    def test_pink(self):
        assert _normalize_artist("p!nk") == "pnk"

    # ── Cross-variant matching ───────────────────────────────────────────────

    def test_the_cars_matches_cars(self):
        assert _normalize_artist("the cars") == _normalize_artist("cars")

    def test_hall_and_oates_matches_ampersand(self):
        assert _normalize_artist("hall and oates") == _normalize_artist("hall & oates")

    def test_bob_seger_variants(self):
        assert _normalize_artist("bob seger and the silver bullet band") == \
               _normalize_artist("bob seger & the silver bullet band")

    # ── Names with numbers ───────────────────────────────────────────────────

    def test_numbers_preserved(self):
        assert _normalize_artist("blink-182") == "blink182"

    def test_number_only_name(self):
        assert _normalize_artist("10cc") == "10cc"

    # ── Negative cases (must NOT collide) ────────────────────────────────────

    def test_mr_big_not_mr_mister(self):
        assert _normalize_artist("mr. big") != _normalize_artist("mr. mister")

    def test_cars_not_carts(self):
        assert _normalize_artist("the cars") != _normalize_artist("carts")

    # ── Idempotency ──────────────────────────────────────────────────────────

    @pytest.mark.parametrize("name", [
        "the cars", "hall & oates", "mr. mister", "mister mister",
        "ac/dc", "beyoncé", "!!!", "the the", "radiohead", "blink-182",
    ])
    def test_idempotent(self, name):
        """Normalizing an already-normalized name should return the same result."""
        assert _normalize_artist(_normalize_artist(name)) == _normalize_artist(name)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_adaptive_engine.py::TestNormalizeArtist -v`

Expected: ImportError — `_normalize_artist` not defined.

- [ ] **Step 3: Implement `_normalize_artist()`**

Add to `adaptive_engine.py` after the existing imports (after `log = logging.getLogger(...)`, before `DEFAULT_ALPHA`):

```python
import functools as _functools
import re as _re
import unicodedata as _unicodedata

_ABBREV_MAP = {"mister": "mr", "saint": "st", "junior": "jr", "senior": "sr"}


@_functools.lru_cache(maxsize=8192)
def _normalize_artist(name: str) -> str:
    """Normalize an artist name for dedup/blocklist comparison.

    Strips 'the ' prefix (with length guard), normalizes '&' -> 'and',
    decomposes Unicode, strips punctuation, applies abbreviation map.
    Falls back to lowered original if normalization produces empty string.
    """
    s = name.lower().strip()
    if not s:
        return s

    # Unicode decomposition: Beyoncé -> Beyonce, d´arby -> d arby
    s = _unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not _unicodedata.combining(c))

    # Strip 'the ' prefix (guard: keep if result < 2 chars)
    stripped = _re.sub(r'^the\s+', '', s)
    if len(stripped) >= 2:
        s = stripped

    # Replace & with ' and ' (space-insensitive)
    s = _re.sub(r'\s*&\s*', ' and ', s)

    # Strip punctuation
    s = _re.sub(r'[^\w\s]', '', s)

    # Collapse whitespace
    s = _re.sub(r'\s+', ' ', s).strip()

    # Apply abbreviation map
    words = s.split()
    words = [_ABBREV_MAP.get(w, w) for w in words]
    s = ' '.join(words)

    # Fallback: if normalization destroyed the name, use lowered original
    if not s:
        return name.lower().strip()

    return s
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_adaptive_engine.py::TestNormalizeArtist -v`

Expected: All pass.

- [ ] **Step 5: Run full existing test suite for regression**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/ -v --tb=short`

Expected: All existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add adaptive_engine.py tests/test_adaptive_engine.py
git commit -m "feat: add _normalize_artist() with unit tests (issue #18)"
```

---

### Task 2: Non-artist term filter + tests

**Files:**
- Modify: `adaptive_engine.py` (near top, after `_normalize_artist`)
- Modify: `tests/test_adaptive_engine.py` (new test class)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_adaptive_engine.py`:

```python
from adaptive_engine import _NON_ARTIST_TERMS, _is_non_artist_term


class TestNonArtistFilter:
    """Non-artist term filtering (genre tags, song titles, decade labels)."""

    def test_decade_label_filtered(self):
        assert _is_non_artist_term("80s") is True

    def test_genre_filtered(self):
        assert _is_non_artist_term("classic rock") is True

    def test_song_title_filtered(self):
        assert _is_non_artist_term("down under") is True

    def test_real_artist_not_filtered(self):
        assert _is_non_artist_term("radiohead") is False

    def test_partial_match_safe(self):
        """'metal church' must NOT be filtered even though 'metal' could be a genre."""
        assert _is_non_artist_term("metal church") is False

    def test_pre_normalization(self):
        """'The Punk' lowered is 'the punk', not in the set. Must not be filtered."""
        assert _is_non_artist_term("the punk") is False

    def test_case_insensitive(self):
        assert _is_non_artist_term("Classic Rock") is True

    def test_synth_pop(self):
        assert _is_non_artist_term("synth pop") is True

    def test_new_wave(self):
        assert _is_non_artist_term("new wave") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_adaptive_engine.py::TestNonArtistFilter -v`

Expected: ImportError.

- [ ] **Step 3: Implement the filter**

Add to `adaptive_engine.py` after `_normalize_artist`:

```python
_NON_ARTIST_TERMS = frozenset({
    "80s", "90s", "70s", "60s",
    "classic rock", "new wave", "post punk", "synth pop",
    "down under", "rocket man",
})


def _is_non_artist_term(name: str) -> bool:
    """Check if a candidate name is a known non-artist term (genre, decade, song title).

    Checked against the raw lowercased name (before artist normalization)
    to avoid false positives from normalization collapsing real artist names.
    """
    return name.lower().strip() in _NON_ARTIST_TERMS
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_adaptive_engine.py::TestNonArtistFilter -v`

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add adaptive_engine.py tests/test_adaptive_engine.py
git commit -m "feat: add non-artist term filter (issue #18)"
```

---

### Task 3: Normalize `_load_offered_tracks` + cross-round migration test

**Files:**
- Modify: `adaptive_engine.py:49-70` (`_load_offered_tracks`)
- Modify: `tests/test_adaptive_engine.py` (new test)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_adaptive_engine.py`:

```python
from adaptive_engine import _load_offered_tracks


class TestLoadOfferedTracksArtistNormalization:
    """Cross-round migration: old offered_tracks with raw artist names
    must produce normalized-artist keys in the dedup set."""

    def test_normalized_artist_keys_in_set(self, tmp_path):
        """Pre-normalization entry ('mr. mister', 'is it love') should produce
        a normalized-artist key ('mr mr', 'is it love') in the set."""
        offered = tmp_path / "offered_tracks.json"
        offered.write_text(json.dumps({
            "version": 1,
            "tracks": [
                {"artist": "mr. mister", "track": "is it love", "round": 1},
                {"artist": "the cars", "track": "just what i needed", "round": 1},
            ]
        }))
        track_set, entries = _load_offered_tracks(offered)

        # Raw keys present (existing behavior)
        assert ("mr. mister", "is it love") in track_set
        assert ("the cars", "just what i needed") in track_set

        # Normalized-artist keys present (new behavior)
        assert ("mr mr", "is it love") in track_set
        assert ("cars", "just what i needed") in track_set

    def test_normalized_artist_plus_normalized_track(self, tmp_path):
        """Both artist AND track normalization should be applied together."""
        offered = tmp_path / "offered_tracks.json"
        offered.write_text(json.dumps({
            "version": 1,
            "tracks": [
                {"artist": "the cars", "track": "Just What I Needed (Live)", "round": 1},
            ]
        }))
        track_set, _ = _load_offered_tracks(offered)

        # Normalized artist + normalized track
        from signal_experiment import _normalize_for_match
        assert ("cars", _normalize_for_match("Just What I Needed (Live)")) in track_set
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_adaptive_engine.py::TestLoadOfferedTracksArtistNormalization -v`

Expected: FAIL — normalized-artist keys not in set.

- [ ] **Step 3: Update `_load_offered_tracks`**

In `adaptive_engine.py`, modify `_load_offered_tracks` (around lines 49-70). Replace the track_set building loop:

```python
def _load_offered_tracks(path: pathlib.Path) -> tuple[set, list]:
    """Load previously offered tracks. Returns (set of (artist, track), raw entries list).

    Adds raw, track-normalized, artist-normalized, and both-normalized keys
    so cross-round dedup catches formatting variants."""
    if not path.exists():
        return set(), []
    try:
        from signal_experiment import _normalize_for_match
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get("tracks", [])
        track_set = set()
        for t in entries:
            raw_artist = t["artist"]
            raw_track = t["track"]
            norm_artist = _normalize_artist(raw_artist)
            norm_track = _normalize_for_match(raw_track)
            # 4 key variants: raw/raw, raw/norm_track, norm_artist/raw, norm_artist/norm_track
            track_set.add((raw_artist, raw_track))
            track_set.add((raw_artist, norm_track))
            track_set.add((norm_artist, raw_track))
            track_set.add((norm_artist, norm_track))
        log.debug("  _load_offered_tracks: %d entries -> %d set keys from %s",
                  len(entries), len(track_set), path)
        return track_set, entries
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log.warning("Corrupt offered_tracks.json, starting fresh: %s", e)
        return set(), []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_adaptive_engine.py::TestLoadOfferedTracksArtistNormalization tests/test_adaptive_engine.py::TestDedupNormalizationConsistency -v`

Expected: All pass (new + existing dedup tests).

- [ ] **Step 5: Commit**

```bash
git add adaptive_engine.py tests/test_adaptive_engine.py
git commit -m "feat: add artist normalization to _load_offered_tracks (issue #18)"
```

---

### Task 4: Normalize library pre-seed + dedup integration test

**Files:**
- Modify: `adaptive_engine.py:1120-1128` (library pre-seed)
- Modify: `adaptive_engine.py:1185-1188` (cross-round dedup)
- Modify: `adaptive_engine.py:1214-1221` (post-resolution dedup)
- Modify: `adaptive_engine.py:1233-1246` (pre-add failsafe)
- Modify: `adaptive_engine.py:1263-1274` (post-add bookkeeping)
- Modify: `tests/test_adaptive_engine.py` (integration test)

- [ ] **Step 1: Write the failing integration test**

These tests exercise the actual `_load_offered_tracks` + library pre-seed code paths end-to-end, not manually constructed sets.

Add to `tests/test_adaptive_engine.py`:

```python
class TestArtistNormalizationDedup:
    """Integration: artist name variants caught by combined load + pre-seed dedup."""

    def test_load_plus_preseed_catches_mr_mister(self, tmp_path):
        """offered_tracks has ('mr mister', 'is it love') from a prior round.
        Library also has it. Candidate 'mr. mister' / 'is it love' must be blocked
        by the offered_set built from _load_offered_tracks."""
        from signal_experiment import _normalize_for_match

        # Write offered_tracks with raw artist name from old round
        offered = tmp_path / "offered_tracks.json"
        offered.write_text(json.dumps({
            "version": 1,
            "tracks": [{"artist": "mr mister", "track": "is it love", "round": 1}]
        }))
        offered_set, _ = _load_offered_tracks(offered)

        # Candidate arrives as "mr. mister" — check all key variants
        candidate_artist = "mr. mister"
        candidate_track = "is it love"
        key = (candidate_artist.lower(), candidate_track.lower())
        norm_key = (candidate_artist.lower(), _normalize_for_match(candidate_track))
        anorm_key = (_normalize_artist(candidate_artist), candidate_track.lower())
        anorm_norm_key = (_normalize_artist(candidate_artist), _normalize_for_match(candidate_track))

        assert (key in offered_set or norm_key in offered_set
                or anorm_key in offered_set or anorm_norm_key in offered_set), \
            f"Dedup missed 'mr. mister' variant in offered_tracks loaded from disk"

    def test_load_catches_the_prefix_variant(self, tmp_path):
        """offered_tracks has ('the cars', 'just what i needed').
        Candidate 'cars' / 'just what i needed' must be blocked."""
        offered = tmp_path / "offered_tracks.json"
        offered.write_text(json.dumps({
            "version": 1,
            "tracks": [{"artist": "the cars", "track": "just what i needed", "round": 1}]
        }))
        offered_set, _ = _load_offered_tracks(offered)

        anorm_key = (_normalize_artist("cars"), "just what i needed")
        assert anorm_key in offered_set
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_adaptive_engine.py::TestArtistNormalizationDedup -v`

Expected: FAIL — `_load_offered_tracks` hasn't been updated yet in Task 3, but these tests depend on it. If Task 3 is already complete, these should pass. If running tasks in order, these confirm Task 3's changes work end-to-end.

- [ ] **Step 3: Update library pre-seed**

In `adaptive_engine.py`, modify the library pre-seed loop (around lines 1120-1128):

```python
    library_track_count = 0
    for track in track_metadata:
        t_artist = (track.get("artist") or "").lower().strip()
        t_name = (track.get("name") or "").lower().strip()
        if t_artist and t_name:
            norm_a = _normalize_artist(t_artist)
            norm_t = _normalize_for_match(t_name)
            offered_set.add((t_artist, t_name))
            offered_set.add((t_artist, norm_t))
            offered_set.add((norm_a, t_name))
            offered_set.add((norm_a, norm_t))
            library_track_count += 1
    log.info("  Pre-seeded %d library tracks into dedup set.", library_track_count)
```

- [ ] **Step 4: Update cross-round dedup check**

In `adaptive_engine.py`, modify the dedup check (around lines 1185-1188):

```python
            # Cross-round dedup
            key = (artist.lower(), track_name.lower())
            norm_key = (artist.lower(), _normalize_for_match(track_name))
            anorm_key = (_normalize_artist(artist), track_name.lower())
            anorm_norm_key = (_normalize_artist(artist), _normalize_for_match(track_name))
            if key in offered_set or norm_key in offered_set or anorm_key in offered_set or anorm_norm_key in offered_set:
                continue
```

Also update the diagnostic log that follows (around lines 1192-1199) to include the new keys:

```python
            if log.isEnabledFor(logging.DEBUG):
                artist_entries_in_set = [
                    entry for entry in offered_set if entry[0] == artist.lower()
                    or entry[0] == _normalize_artist(artist)
                ]
                log.debug("    DEDUP PASS: key=%s in_set=%s | norm=%s in_set=%s | "
                          "anorm=%s in_set=%s | artist_entries=%d: %s",
                          key, key in offered_set, norm_key, norm_key in offered_set,
                          anorm_key, anorm_key in offered_set,
                          len(artist_entries_in_set), artist_entries_in_set[:10])
```

- [ ] **Step 5: Update post-resolution dedup check**

In `adaptive_engine.py`, modify the post-resolution check (around lines 1214-1221):

```python
            canon_artist = (result.canonical_artist or artist).lower()
            canon_track = result.canonical_track or track_name
            canon_key = (canon_artist, canon_track.lower())
            canon_norm = (canon_artist, _normalize_for_match(canon_track))
            canon_anorm = (_normalize_artist(canon_artist), canon_track.lower())
            canon_anorm_norm = (_normalize_artist(canon_artist), _normalize_for_match(canon_track))
            if (canon_key in offered_set or canon_norm in offered_set
                    or canon_anorm in offered_set or canon_anorm_norm in offered_set):
                log.debug("  Skipped %s — %s (canonical match after iTunes "
                          "resolution from '%s')",
                          result.canonical_artist, result.canonical_track,
                          track_name)
                continue
```

- [ ] **Step 6: Update pre-add failsafe**

In `adaptive_engine.py`, modify the pre-add failsafe (around lines 1233-1246):

```python
            if (canon_key in offered_tracks or canon_norm in offered_tracks
                    or canon_anorm in offered_tracks or canon_anorm_norm in offered_tracks):
                if log.isEnabledFor(logging.DEBUG):
                    matching = [e for e in offered_tracks
                                if e[0] in (canon_artist, artist.lower(),
                                            _normalize_artist(canon_artist),
                                            _normalize_artist(artist))]
                else:
                    matching = []
                log.warning("  FAILSAFE PRE-ADD: duplicate caught for %s — %s "
                            "(canon_key=%s, canon_norm=%s, canon_anorm=%s). "
                            "Matching entries in offered_tracks: %s",
                            canon_artist, canon_track, canon_key, canon_norm,
                            canon_anorm, matching[:10])
                continue
```

- [ ] **Step 7: Update post-add bookkeeping**

In `adaptive_engine.py`, modify the all_keys expansion (around lines 1270-1274):

```python
                    all_keys = (
                        key, norm_key, anorm_key, anorm_norm_key,
                        actual_key, actual_norm,
                        (_normalize_artist(actual_artist), actual_track.lower()),
                        (_normalize_artist(actual_artist), _normalize_for_match(actual_track)),
                        canon_key, canon_norm, canon_anorm, canon_anorm_norm,
                    )
                    offered_tracks.update(all_keys)
                    offered_set.update(all_keys)
```

Also update the post-add failsafe check (around lines 1263) to include normalized variants:

```python
                actual_key = (actual_artist.lower(), actual_track.lower())
                actual_norm = (actual_artist.lower(),
                               _normalize_for_match(actual_track))
                actual_anorm = (_normalize_artist(actual_artist), actual_track.lower())
                actual_anorm_norm = (_normalize_artist(actual_artist),
                                     _normalize_for_match(actual_track))

                if (actual_key in offered_tracks or actual_norm in offered_tracks
                        or actual_anorm in offered_tracks or actual_anorm_norm in offered_tracks):
```

- [ ] **Step 8: Run all dedup tests**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_adaptive_engine.py -k "Dedup or Normalization or Failsafe" -v`

Expected: All pass.

- [ ] **Step 9: Run full test suite for regression**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/ -v --tb=short`

Expected: All pass.

- [ ] **Step 10: Commit**

```bash
git add adaptive_engine.py tests/test_adaptive_engine.py
git commit -m "feat: apply artist normalization to build loop dedup (issue #18)"
```

---

### Task 5: Normalize blocklist loading + tests

**Files:**
- Modify: `music_discovery.py:730-770` (blocklist loaders)
- Modify: `adaptive_engine.py:141-182` (`_auto_blocklist_artist`, `_remove_from_blocklist`)
- Modify: `adaptive_engine.py:1053` (`full_blocklist.discard`)
- Modify: `tests/test_adaptive_engine.py` (new test class)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_adaptive_engine.py`:

```python
class TestBlocklistArtistNormalization:
    """Blocklist loading produces normalized keys; rank_candidates uses them."""

    def test_load_user_blocklist_normalized(self, tmp_path):
        """load_user_blocklist returns normalized artist names."""
        from music_discovery import load_user_blocklist
        bl_file = tmp_path / "blocklist.txt"
        bl_file.write_text("The Cars\nhall & oates\n")
        bl = load_user_blocklist(bl_file)
        assert "cars" in bl              # 'the' stripped
        assert "hall and oates" in bl    # '&' -> 'and'

    def test_load_blocklist_json_normalized(self, tmp_path):
        """load_blocklist returns normalized artist names."""
        from music_discovery import load_blocklist
        bl_file = tmp_path / "blocklist.json"
        bl_file.write_text(json.dumps({"blocked": ["The Pretenders", "mr. mister"]}))
        bl = load_blocklist(bl_file)
        assert "pretenders" in bl        # 'the' stripped
        assert "mr mr" in bl            # period stripped + abbreviation

    def test_rank_candidates_blocks_variant(self):
        """rank_candidates filters 'the cars' when blocklist has normalized 'cars'.
        Tests the actual production path: raw score keys + normalized blocklist."""
        scores = {"the cars": 0.9, "radiohead": 0.8}
        blocklist = {_normalize_artist("the cars")}  # {"cars"}
        ranked = rank_candidates(scores, blocklist=blocklist)
        artist_names = [name for _, name in ranked]
        assert "the cars" not in artist_names
        assert "radiohead" in artist_names
```

- [ ] **Step 2 (revised): Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_adaptive_engine.py::TestBlocklistArtistNormalization -v`

Expected: FAIL — `load_user_blocklist` returns raw lowered names, not normalized.

- [ ] **Step 3: Modify blocklist loaders in `music_discovery.py`**

Update `load_user_blocklist` (line 746):

```python
def load_user_blocklist(path):
    """Load a plain-text blocklist file (one artist per line).
    Blank lines and lines starting with # are ignored.
    Names are normalized for case/punctuation-insensitive matching.
    Returns an empty set if file does not exist."""
    from adaptive_engine import _normalize_artist
    path = pathlib.Path(path)
    if not path.exists():
        return set()
    names = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                names.add(_normalize_artist(line))
    return names
```

Update `load_blocklist` (line 730):

```python
def load_blocklist(path):
    """Load file-based blocklist. Returns a set of normalized names.

    NOTE: Normalization is applied at load time only (for comparison).
    save_blocklist still writes the original raw names from the blocked set.
    Do NOT feed the normalized output of this function back to save_blocklist.
    """
    from adaptive_engine import _normalize_artist
    path = pathlib.Path(path)
    if not path.exists():
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return set(_normalize_artist(name) for name in json.load(f).get("blocked", []))
    except (json.JSONDecodeError, KeyError):
        return set()
```

**IMPORTANT:** `save_blocklist` (line 741) must NOT be modified — it writes raw names to the JSON file. The normalized set returned by `load_blocklist` is for comparison only and should never be passed back to `save_blocklist`. Verify that no code path feeds `full_blocklist` (which now contains normalized keys) back into `save_blocklist`.

- [ ] **Step 4: Normalize candidate names at blocklist check points**

In `adaptive_engine.py`, wherever `candidate in full_blocklist` appears, normalize the candidate:

**Line 676 area (seed sanity check):**
```python
        if _normalize_artist(candidate) in full_blocklist:
            continue
```

**Line 975 area (build scoring):**
```python
        if _normalize_artist(candidate) in full_blocklist:
            continue
```

**Line 351 (`rank_candidates`):**
```python
        if _normalize_artist(artist) in blocklist:
            continue
```

**Line 1044 (re-check loop):**
```python
        if _normalize_artist(candidate) not in full_blocklist:
            continue
```

**Line 1053 (`full_blocklist.discard`):**
```python
            _remove_from_blocklist(blocklist_path, candidate)
            full_blocklist.discard(_normalize_artist(candidate))
```

- [ ] **Step 5: Normalize `_auto_blocklist_artist` and `_remove_from_blocklist`**

In `_auto_blocklist_artist` (line 141), normalize the existence check:

```python
def _auto_blocklist_artist(blocklist_path: pathlib.Path, artist: str, round_num: int):
    """Append an artist to ai_blocklist.txt if not already present."""
    existing = set()
    if blocklist_path.exists():
        for line in blocklist_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                existing.add(_normalize_artist(stripped))

    if _normalize_artist(artist) in existing:
        return

    with open(blocklist_path, "a", encoding="utf-8") as f:
        f.write(f"# auto-blocklisted round {round_num}:\n")
        f.write(f"{artist}\n")
    log.warning("Auto-blocklisted \"%s\" — not found on Apple Music for %d consecutive rounds",
                artist, STRIKE_THRESHOLD)
```

In `_remove_from_blocklist` (line 169), normalize the comparison:

```python
def _remove_from_blocklist(blocklist_path: pathlib.Path, artist: str):
    """Remove an auto-blocklisted artist and its comment from the blocklist file."""
    if not blocklist_path.exists():
        return
    lines = blocklist_path.read_text(encoding="utf-8").splitlines()
    target = _normalize_artist(artist)
    new_lines = []
    for line in lines:
        if line.strip() and not line.strip().startswith("#") and _normalize_artist(line.strip()) == target:
            if new_lines and new_lines[-1].strip().startswith("# auto-blocklisted"):
                new_lines.pop()
            continue
        new_lines.append(line)
    blocklist_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    log.info("Re-checked \"%s\" — now available on Apple Music, removed from auto-blocklist", artist)
```

- [ ] **Step 6: Run tests**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_adaptive_engine.py::TestBlocklistArtistNormalization tests/test_music_discovery.py -k "blocklist" -v`

Expected: All pass.

- [ ] **Step 7: Run full test suite for regression**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/ -v --tb=short`

Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add adaptive_engine.py music_discovery.py tests/test_adaptive_engine.py
git commit -m "feat: normalize blocklist loading and matching (issue #18)"
```

---

### Task 6: Normalize strike tracking + cooldown + tests

**Files:**
- Modify: `adaptive_engine.py:106-133` (`_evaluate_artist_strikes`)
- Modify: `adaptive_engine.py:223-249` (`check_cooldown`)
- Modify: `adaptive_engine.py:160-166` (`_should_recheck_artist`)
- Modify: `adaptive_engine.py:1046-1057` (re-check strike lookups)
- Modify: `tests/test_adaptive_engine.py` (new tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_adaptive_engine.py`:

```python
class TestStrikeNormalization:
    """Strike tracking uses normalized artist keys."""

    def test_strikes_keyed_by_normalized_name(self):
        """Strikes for 'mr. mister' should be found when checking 'mr mister'."""
        from collections import namedtuple
        SearchResult = namedtuple("SearchResult", ["store_id", "searched_ok"])

        strikes = {}
        results_not_found = [SearchResult(store_id=None, searched_ok=True)]

        from adaptive_engine import _evaluate_artist_strikes
        _evaluate_artist_strikes(strikes, "mr. mister", results_not_found, 1)
        _evaluate_artist_strikes(strikes, "mr. mister", results_not_found, 2)

        norm_key = _normalize_artist("mr mister")
        assert norm_key in strikes
        assert strikes[norm_key]["count"] == 2

    def test_strikes_reset_on_found_with_variant(self):
        """Finding tracks for 'mr mister' should reset strikes stored under 'mr. mister'."""
        from collections import namedtuple
        SearchResult = namedtuple("SearchResult", ["store_id", "searched_ok"])

        strikes = {}
        not_found = [SearchResult(store_id=None, searched_ok=True)]
        found = [SearchResult(store_id="12345", searched_ok=True)]

        from adaptive_engine import _evaluate_artist_strikes
        _evaluate_artist_strikes(strikes, "mr. mister", not_found, 1)
        _evaluate_artist_strikes(strikes, "mr. mister", not_found, 2)
        # Now find under variant name — should reset
        _evaluate_artist_strikes(strikes, "mr mister", found, 3)

        norm_key = _normalize_artist("mr mister")
        assert strikes[norm_key]["count"] == 0

    def test_should_recheck_with_variant(self):
        """_should_recheck_artist with variant name should find existing strikes."""
        from adaptive_engine import _should_recheck_artist, RECHECK_COOLDOWN
        strikes = {
            _normalize_artist("the cars"): {"count": 3, "last_round": 1, "last_recheck": 0}
        }
        assert _should_recheck_artist(strikes, "The Cars", RECHECK_COOLDOWN + 1) is True

    def test_load_strikes_migration(self, tmp_path):
        """Loading old strikes with raw keys should migrate to normalized keys."""
        from adaptive_engine import _load_search_strikes
        strikes_file = tmp_path / "search_strikes.json"
        strikes_file.write_text(json.dumps({
            "version": 1,
            "strikes": {
                "mr. mister": {"count": 2, "last_round": 3, "last_recheck": 0},
                "the cars": {"count": 1, "last_round": 2, "last_recheck": 0},
            }
        }))
        strikes = _load_search_strikes(strikes_file)
        # Should be migrated to normalized keys
        assert "mr mr" in strikes
        assert "cars" in strikes
        assert strikes["mr mr"]["count"] == 2


class TestCooldownNormalization:
    """Cooldown check uses normalized artist names."""

    def test_cooldown_fires_for_the_variant(self):
        """History has 'the cars', candidate is 'cars' — cooldown should fire."""
        history = [
            {"artist_feedback": {"the cars": {"fave_tracks": 0, "tracks_offered": 2}}}
        ]
        # With normalization, 'cars' should match 'the cars' in history
        assert check_cooldown("cars", history, current_round=2, cooldown_rounds=3) is True

    def test_cooldown_skips_when_favorited_variant(self):
        """History has 'the cars' with faves — 'cars' should NOT be cooled down."""
        history = [
            {"artist_feedback": {"the cars": {"fave_tracks": 1, "tracks_offered": 2}}}
        ]
        assert check_cooldown("cars", history, current_round=2, cooldown_rounds=3) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_adaptive_engine.py::TestStrikeNormalization tests/test_adaptive_engine.py::TestCooldownNormalization -v`

Expected: FAIL — strikes not keyed by normalized name; cooldown doesn't find variant.

- [ ] **Step 3: Normalize `_evaluate_artist_strikes`**

In `adaptive_engine.py`, modify `_evaluate_artist_strikes` (line 106):

```python
def _evaluate_artist_strikes(strikes: dict, artist: str,
                              search_results: list, current_round: int) -> bool:
    """Evaluate search results for an artist and update strike counter.
    Returns True if artist should be auto-blocklisted (hit threshold).
    Uses normalized artist name as key for consistent cross-variant tracking."""
    norm = _normalize_artist(artist)
    entry = strikes.get(norm, {"count": 0, "last_round": 0, "last_recheck": 0})

    any_found = any(r.store_id is not None for r in search_results)
    any_searched_ok = any(r.searched_ok for r in search_results)
    all_errored = not any_searched_ok

    if any_found:
        entry["count"] = 0
        entry["last_round"] = current_round
        strikes[norm] = entry
        return False

    if all_errored:
        return False

    # All searched OK but none found
    if entry["last_round"] > 0 and current_round - entry["last_round"] > 1:
        entry["count"] = 0  # reset stale counter

    entry["count"] += 1
    entry["last_round"] = current_round
    strikes[norm] = entry

    return entry["count"] >= STRIKE_THRESHOLD
```

- [ ] **Step 4: Normalize `_should_recheck_artist`**

In `adaptive_engine.py`, modify `_should_recheck_artist` (line 160):

```python
def _should_recheck_artist(strikes: dict, artist: str, current_round: int) -> bool:
    """Check if a blocklisted artist should be re-tested."""
    entry = strikes.get(_normalize_artist(artist))
    if not entry:
        return False
    last_recheck = entry.get("last_recheck", 0)
    return current_round - last_recheck >= RECHECK_COOLDOWN
```

- [ ] **Step 5: Normalize re-check strike lookups**

In `adaptive_engine.py`, around lines 1046-1057, normalize the strike key operations:

```python
        # Eligible for re-check
        catalog = fetch_artist_catalog(candidate)
        norm_cand = _normalize_artist(candidate)
        strikes.setdefault(norm_cand, {"count": 3, "last_round": 0, "last_recheck": 0})
        if catalog:
            _remove_from_blocklist(blocklist_path, candidate)
            full_blocklist.discard(_normalize_artist(candidate))
            rechecked += 1
            log.info("  Re-check passed for %s, re-entering candidate pool", candidate)
        else:
            strikes[norm_cand]["last_recheck"] = current_round
```

- [ ] **Step 6: Add strike data migration to `_load_search_strikes`**

In `adaptive_engine.py`, modify `_load_search_strikes` to migrate old raw-keyed entries to normalized keys on load. This ensures existing strike counters survive the deployment:

```python
def _load_search_strikes(path: pathlib.Path) -> dict:
    """Load search strikes, migrating raw keys to normalized keys."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get("strikes", {})
        # Migrate: re-key entries using _normalize_artist.
        # If two raw keys collapse to the same normalized key, keep the one with higher count.
        migrated = {}
        for artist, entry in raw.items():
            norm = _normalize_artist(artist)
            if norm in migrated:
                if entry.get("count", 0) > migrated[norm].get("count", 0):
                    migrated[norm] = entry
            else:
                migrated[norm] = entry
        return migrated
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}
```

- [ ] **Step 7: Normalize `check_cooldown`**

In `adaptive_engine.py`, modify `check_cooldown` (line 223):

```python
def check_cooldown(
    artist: str,
    history_rounds: list,
    current_round: int,
    cooldown_rounds: int = DEFAULT_COOLDOWN_ROUNDS,
) -> bool:
    """Returns True if artist should be skipped (offered recently, not favorited).

    Uses normalized artist names so 'the cars' and 'cars' are treated as the same.
    """
    norm = _normalize_artist(artist)
    for round_num, rnd in enumerate(history_rounds, start=1):
        if current_round - round_num > cooldown_rounds:
            continue
        if current_round - round_num <= 0:
            continue
        artist_fb = rnd.get("artist_feedback", {})
        # Build normalized lookup once per round call. With lru_cache on
        # _normalize_artist, dict construction is cheap (~40 cache hits per round).
        norm_fb = {_normalize_artist(k): v for k, v in artist_fb.items()}
        fb = norm_fb.get(norm)
        if fb is not None:
            if fb.get("fave_tracks", 0) > 0:
                return False
            else:
                return True
    return False
```

- [ ] **Step 8: Run tests**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_adaptive_engine.py::TestStrikeNormalization tests/test_adaptive_engine.py::TestCooldownNormalization tests/test_adaptive_engine.py::TestCheckCooldown -v`

Expected: All pass (new + existing cooldown tests).

- [ ] **Step 9: Run full test suite for regression**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/ -v --tb=short`

Expected: All pass.

- [ ] **Step 10: Commit**

```bash
git add adaptive_engine.py tests/test_adaptive_engine.py
git commit -m "feat: normalize strike tracking and cooldown lookups (issue #18)"
```

---

### Task 7: Normalize candidate generation, scoring, and overrides

**Files:**
- Modify: `adaptive_engine.py:640-644` (seed candidate generation)
- Modify: `adaptive_engine.py:964-967` (build candidate generation)
- Modify: `adaptive_engine.py:205-220` (`apply_overrides`)
- Modify: `adaptive_engine.py:1079-1080` (library_artists pool split)
- Modify: `tests/test_adaptive_engine.py` (new tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_adaptive_engine.py`:

```python
class TestCandidateGenerationNormalization:
    """Candidate generation filters non-artist terms and normalizes names."""

    def test_non_artist_filtered_from_candidates(self):
        """'80s' and 'classic rock' should be removed from candidate set."""
        # Simulate scrape cache with non-artist terms
        scrape_cache = {
            "metallica": {"slayer": 0.8, "80s": 0.5, "classic rock": 0.3},
        }
        all_candidates = set()
        for artist, neighbors in scrape_cache.items():
            for n in neighbors.keys():
                if not _is_non_artist_term(n):
                    all_candidates.add(n.lower())
        assert "slayer" in all_candidates
        assert "80s" not in all_candidates
        assert "classic rock" not in all_candidates


class TestApplyOverridesNormalization:
    """apply_overrides uses normalized keys for matching."""

    def test_override_matches_variant(self):
        """Pin for 'The Cars' should match candidate 'cars'."""
        scores = {"cars": 0.5}
        overrides = {"pins": {"The Cars": 1.0}}
        result = apply_overrides(scores, overrides)
        assert result.get("cars") == 1.0 or result.get(_normalize_artist("the cars")) == 1.0
```

- [ ] **Step 2: Run tests to verify behavior**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_adaptive_engine.py::TestCandidateGenerationNormalization tests/test_adaptive_engine.py::TestApplyOverridesNormalization -v`

- [ ] **Step 3: Add non-artist filtering to candidate generation**

In `adaptive_engine.py`, modify the candidate generation at lines 640-644 (seed path):

```python
    all_candidates = set()
    non_artist_filtered = []
    for artist, neighbors in scrape_cache.items():
        for n in neighbors.keys():
            n_lower = n.lower()
            if _is_non_artist_term(n_lower):
                non_artist_filtered.append(n_lower)
                continue
            all_candidates.add(n_lower)
    # Normalize both sides for the subtraction so "the cars" matches "cars"
    norm_lib = {_normalize_artist(a) for a in library_artists}
    all_candidates = {c for c in all_candidates if _normalize_artist(c) not in norm_lib}
    if non_artist_filtered:
        log.info("  Filtered %d non-artist candidates: %s",
                 len(non_artist_filtered), ", ".join(sorted(set(non_artist_filtered))))
```

Apply the same pattern at lines 964-967 (build path):

```python
    all_candidates = set()
    non_artist_filtered = []
    for artist, neighbors in scrape_cache.items():
        for n in neighbors.keys():
            n_lower = n.lower()
            if _is_non_artist_term(n_lower):
                non_artist_filtered.append(n_lower)
                continue
            all_candidates.add(n_lower)
    if non_artist_filtered:
        log.info("  Filtered %d non-artist candidates: %s",
                 len(non_artist_filtered), ", ".join(sorted(set(non_artist_filtered))))
```

- [ ] **Step 4: Normalize `apply_overrides`**

In `adaptive_engine.py`, modify `apply_overrides` (line 205):

```python
def apply_overrides(scores: dict, overrides: dict) -> dict:
    """Apply manual pin overrides. Returns new dict.

    overrides["pins"] maps artist names to floats:
      - positive pin (e.g. 1.0) forces that score
      - negative pin (e.g. -1.0) suppresses to 0.0
    Uses normalized artist names for matching.
    """
    pins = overrides.get("pins", {})
    result = dict(scores)
    # Build normalized -> raw key mapping for scores
    norm_to_raw = {}
    for raw_key in result:
        norm_to_raw.setdefault(_normalize_artist(raw_key), []).append(raw_key)
    for artist, pin_value in pins.items():
        norm_pin = _normalize_artist(artist)
        # Apply to all raw keys that match the normalized pin
        targets = norm_to_raw.get(norm_pin, [])
        for target in targets:
            if pin_value < 0:
                result[target] = 0.0
            else:
                result[target] = pin_value
        # If no match in existing scores, add with the lowered key (original behavior)
        if not targets:
            artist_lower = artist.strip().lower()
            if pin_value < 0:
                result[artist_lower] = 0.0
            else:
                result[artist_lower] = pin_value
    return result
```

- [ ] **Step 5: Normalize `library_artists` for pool split**

In `adaptive_engine.py`, around lines 1079-1080 where `new_pool` and `lib_pool` are built, normalize the comparison:

```python
    # Build normalized library_artists set for pool split
    norm_library_artists = {_normalize_artist(a) for a in library_artists}

    new_pool = [(s, a) for s, a in ranked if _normalize_artist(a) not in norm_library_artists]
    lib_pool = [(s, a) for s, a in ranked if _normalize_artist(a) in norm_library_artists]
```

Also normalize the tag at line 1298:

```python
        if added_count > 0:
            tag = "library" if _normalize_artist(artist) in norm_library_artists else "new"
            log.info("  Added %d tracks for %s [%s]", added_count, artist, tag)
```

- [ ] **Step 6: Run tests**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_adaptive_engine.py -k "Candidate or Override" -v`

Expected: All pass.

- [ ] **Step 7: Run full test suite for regression**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/ -v --tb=short`

Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add adaptive_engine.py tests/test_adaptive_engine.py
git commit -m "feat: normalize candidate generation, overrides, and pool split (issue #18)"
```

---

### Task 8: Normalize affinity graph nodes

**Files:**
- Modify: `adaptive_engine.py:453-456` (seed graph edges)
- Modify: `adaptive_engine.py:474-476` (seed Last.fm edges)
- Modify: `adaptive_engine.py:1548-1570` (expansion graph edges)
- Modify: `adaptive_engine.py:680-685` (scrape_cache proximity lookup)
- Modify: `adaptive_engine.py:980-984` (build scoring proximity lookup)

This is a higher-risk change because graph node names flow into scoring, candidate ranking, and explanation generation. The approach: normalize artist names when they become graph keys, so `"the cars"` and `"cars"` merge into one node. The scrape_cache lookups also need to check both raw and normalized keys.

- [ ] **Step 1: Normalize graph edge insertion in seed mode**

In `adaptive_engine.py`, modify lines 454-456:

```python
    for artist, neighbors in scrape_cache.items():
        for neighbor, weight in neighbors.items():
            graph.add_edge_musicmap(_normalize_artist(artist), _normalize_artist(neighbor), weight)
            mm_edges += 1
```

And lines 474-476:

```python
                    if sim_name and match_score > 0:
                        graph.add_edge_lastfm(_normalize_artist(artist), _normalize_artist(sim_name), match_score)
                        lfm_edges += 1
```

- [ ] **Step 2: Normalize graph edge insertion in seed expansion**

In `adaptive_engine.py`, modify lines 1549-1550:

```python
        for neighbor, weight in similar.items():
            graph.add_edge_musicmap(_normalize_artist(artist), _normalize_artist(neighbor), weight)
            mm_edges_added += 1
```

And lines 1568-1570:

```python
                    if sim_name and match_score > 0:
                        graph.add_edge_lastfm(_normalize_artist(artist), _normalize_artist(sim_name), match_score)
                        lfm_edges_added += 1
```

- [ ] **Step 3: Normalize proximity lookups in scoring**

In `adaptive_engine.py`, modify the proximity lookup at lines 680-685 (seed sanity check):

```python
        proximities = {}
        for seed in library_artists:
            seed_data = scrape_cache.get(seed, {})
            prox = seed_data.get(candidate, 0.0)
            if prox > 0:
                proximities[_normalize_artist(seed)] = {_normalize_artist(candidate): prox}
```

And at lines 980-984 (build scoring):

```python
        proximities = {}
        for seed in library_artists:
            seed_data = scrape_cache.get(seed, {})
            prox = seed_data.get(candidate, 0.0)
            if prox > 0:
                proximities[_normalize_artist(seed)] = {_normalize_artist(candidate): prox}
```

- [ ] **Step 4: Normalize library_artists used as graph seed keys**

In `adaptive_engine.py`, around line 426 and 814-817, normalize the library_artists set:

At line 426:
```python
    library_artists = set(favorites.keys()) | set(playcounts.keys()) | set(playlists.keys()) | set(ratings.keys())
    # Also build normalized set for graph/scoring lookups
    norm_library_artists = {_normalize_artist(a) for a in library_artists}
```

At line 814-817:
```python
    library_artists = (
        set(favorites.keys()) | set(playcounts.keys())
        | set(playlists.keys()) | set(ratings.keys())
    )
    norm_library_artists = {_normalize_artist(a) for a in library_artists}
```

- [ ] **Step 5: Run full test suite for regression**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/ -v --tb=short`

Expected: All pass.

- [ ] **Step 6: Write graph normalization test**

Add to `tests/test_adaptive_engine.py`:

```python
class TestGraphArtistNormalization:
    """Affinity graph merges variant artist names into single nodes."""

    def test_the_prefix_variants_merge(self):
        """'the cars' and 'cars' should be the same graph node."""
        from affinity_graph import AffinityGraph
        graph = AffinityGraph()
        graph.add_edge_musicmap(_normalize_artist("metallica"), _normalize_artist("the cars"), 0.8)
        graph.add_edge_musicmap(_normalize_artist("iron maiden"), _normalize_artist("cars"), 0.6)

        # Both edges should target the same node
        propagated = graph.propagate()
        mm = propagated.get("musicmap", {})
        # 'cars' (normalized) should have combined affinity, not two separate entries
        assert "cars" in mm
        assert "the cars" not in mm
```

- [ ] **Step 7: Run test**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_adaptive_engine.py::TestGraphArtistNormalization -v`

Expected: PASS.

- [ ] **Step 8: Run full test suite for regression**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/ -v --tb=short`

Expected: All pass.

- [ ] **Step 9: Commit**

```bash
git add adaptive_engine.py
git commit -m "feat: normalize affinity graph node keys (issue #18)"
```

---

### Task 9: Blocklist + strike data cleanup

**Files:**
- Script to run against `~/.cache/music_discovery/blocklist_cache.json`
- Script to run against `~/.cache/music_discovery/search_strikes.json`

This is a one-time data fix. Create a small cleanup script, run it, verify, then commit only the script (not the data files — those are in `~/.cache`, not in the repo).

- [ ] **Step 1: Write the cleanup script**

Create `scripts/cleanup_false_blocklist.py`:

```python
#!/usr/bin/env python3
"""One-time cleanup: remove false-positive entries from blocklist_cache.json
and search_strikes.json caused by the artist normalization gap (issue #18)."""

import json
import pathlib

CACHE_DIR = pathlib.Path.home() / ".cache" / "music_discovery"

FALSE_POSITIVES = [
    "mister mister",
    "jimi hendrix and the experience",
    "bob seger and the silver bullet band",
    "hall and oates",
    "cars",
    "pretenders",
    "terence trent d\u00b4arby",   # U+00B4 acute accent
    "reo speed wagon",
    "reo speedwagon",
]

def cleanup_blocklist():
    path = CACHE_DIR / "blocklist_cache.json"
    if not path.exists():
        print(f"  {path} not found, skipping.")
        return
    with open(path) as f:
        data = json.load(f)
    blocked = data.get("blocked", [])
    original_count = len(blocked)
    blocked = [a for a in blocked if a.lower() not in {fp.lower() for fp in FALSE_POSITIVES}]
    removed = original_count - len(blocked)
    data["blocked"] = blocked
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  blocklist_cache.json: removed {removed} entries ({original_count} -> {len(blocked)})")

def cleanup_strikes():
    path = CACHE_DIR / "search_strikes.json"
    if not path.exists():
        print(f"  {path} not found, skipping.")
        return
    with open(path) as f:
        data = json.load(f)
    strikes = data.get("strikes", {})
    original_count = len(strikes)
    fp_set = {fp.lower() for fp in FALSE_POSITIVES}
    strikes = {k: v for k, v in strikes.items() if k.lower() not in fp_set}
    removed = original_count - len(strikes)
    data["strikes"] = strikes
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  search_strikes.json: removed {removed} entries ({original_count} -> {len(strikes)})")

if __name__ == "__main__":
    print("Cleaning up false-positive blocklist/strike entries (issue #18)...")
    cleanup_blocklist()
    cleanup_strikes()
    print("Done.")
```

- [ ] **Step 2: Run the cleanup script**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 scripts/cleanup_false_blocklist.py`

Expected output:
```
Cleaning up false-positive blocklist/strike entries (issue #18)...
  blocklist_cache.json: removed 9 entries (40 -> 31)
  search_strikes.json: removed N entries (...)
Done.
```

- [ ] **Step 3: Verify the cleanup**

Run: `python3 -c "import json; d=json.load(open('$HOME/.cache/music_discovery/blocklist_cache.json')); print([a for a in d['blocked'] if 'mister' in a.lower() or 'cars' in a.lower() or 'pretender' in a.lower() or 'reo' in a.lower()])"'`

Expected: Empty list `[]`.

- [ ] **Step 4: Commit the script**

```bash
mkdir -p scripts
git add scripts/cleanup_false_blocklist.py
git commit -m "chore: add one-time blocklist/strike cleanup script (issue #18)"
```

---

### Task 10: Final regression + close issue

- [ ] **Step 1: Run full test suite**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/ -v --tb=short`

Expected: All pass.

- [ ] **Step 2: Run a quick smoke test of the normalization across the whole pipeline**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -c "
from adaptive_engine import _normalize_artist, _is_non_artist_term

# Verify the headline bug cases
assert _normalize_artist('mr. mister') == _normalize_artist('mister mister'), 'Mr. Mister variants must match'
assert _normalize_artist('the cars') == _normalize_artist('cars'), 'The prefix must be stripped'
assert _normalize_artist('hall & oates') == _normalize_artist('hall and oates'), 'Ampersand must normalize'
assert _normalize_artist('terence trent d\u00b4arby') == _normalize_artist(\"terence trent d'arby\"), 'Unicode accent must normalize'

# Verify non-artist filter
assert _is_non_artist_term('80s') is True
assert _is_non_artist_term('classic rock') is True
assert _is_non_artist_term('radiohead') is False
assert _is_non_artist_term('metal church') is False

print('All smoke tests passed.')
"`

Expected: `All smoke tests passed.`

- [ ] **Step 3: Close issue #18**

Run: `gh issue close 18 --comment "Fixed: artist name normalization applied across dedup, blocklist, cooldown, and scoring pipelines. False blocklist entries cleaned up. Non-artist term filter added."`

- [ ] **Step 4: Final commit if any loose changes**

Check `git status` and commit any remaining changes.
