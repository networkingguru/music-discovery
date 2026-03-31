# AI Artist Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Filter AI-generated and fake artists from discovery playlists using a static blocklist, MusicBrainz type check, and Last.fm metadata heuristic.

**Architecture:** Three-layer detection (allowlist → static blocklist → cache → MusicBrainz → Last.fm heuristic → default pass) integrated into `filter_candidates()` as Rule 4. Static blocklist also added to `eval_exclude` in `signal_experiment.py`. Extended `fetch_filter_data()` extracts bio/tags/type from existing API responses.

**Tech Stack:** Python 3, Last.fm API (`artist.getInfo`), MusicBrainz API (MBID lookup + name search fallback), existing `filter_cache.json` caching.

**Spec:** `docs/superpowers/specs/2026-03-31-ai-artist-detection-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `ai_blocklist.txt` | Create | Static list of ~140 known AI/fake artists (collision-audited) |
| `ai_allowlist.txt` | Create | User override file (starts empty with instructions) |
| `music_discovery.py` | Modify | `load_ai_blocklist()`, `load_ai_allowlist()`, `check_ai_artist()`, extend `fetch_filter_data()`, extend `filter_candidates()` |
| `signal_experiment.py` | Modify | Load ai_blocklist/allowlist, add to `eval_exclude`, thread through scoring kwargs |
| `signal_analysis.py` | Modify | Thread `ai_blocklist`/`ai_allowlist` through `_run_scoring()` |
| `tests/test_music_discovery.py` | Modify | Tests for all new/modified functions |
| `tests/test_signal_analysis.py` | Modify | Tests for threading kwargs |

---

### Task 1: Create Static Blocklist and Allowlist Files

**Files:**
- Create: `ai_blocklist.txt`
- Create: `ai_allowlist.txt`

- [ ] **Step 1: Create `ai_blocklist.txt`**

```text
# AI / Fake Artist Blocklist — Music Discovery
# One artist name per line (case-insensitive). Blank lines and # comments are ignored.
# Sources: MBW investigations, SlopTracker.org, Reddit, court filings, journalism.
# See docs/superpowers/specs/2026-03-31-ai-artist-detection-design.md for details.
#
# COLLISION AUDIT: Names removed due to real-artist collisions:
#   Mayhem, Aven, Nora Van Elken, DV8, David Allen, Owen James,
#   Shea, Hermann, Fellows, Callous

# ── MBW "Original 50" (Quiz & Larossi pseudonyms, 2017) ──
Aaron Lansing
Advaitas
Allysa Nelson
Amity Cadet
Amy Yeager
Ana Olgica
Antologie
Benny Bernstein
Benny Treskow
Bon Vie
Caro Utobarto
Charles Bolt
Charlie Key
Christopher Colman
Clay Edwards
Deep Watch
Dylan Francis
Enno Aare
Evelyn Stein
Evolution Of Stars
Gabriel Parker
Giuseppe Galvetti
Greg Barley
Heinz Goldblatt
Hiroshi Yamazaki
Hultana
Jeff Bright Jr
Jonathan Coffey
Jozef Gatysik
Karin Borg
Leon Noel
Lo Mimieux
Martin Fox
Mbo Mentho
Mia Strass
Milos Stavos
Novo Talos
Otto Wahl
Pernilla Mayer
Piotr Miteska
Relajar
Risto Carto
Sam Eber
Samuel Lindon
The 2 Inversions
They Dream By Day
Tony Lieberman
Wilma Harrods

# ── Johan Rohr / Firefly / Chillmi pseudonyms (2022-2024) ──
Adelmar Borrego
Csizmazia Etel
Maya Astrom
Minik Knudsen
Mingmei Hsueh

# ── Epidemic Sound / PFC ghost artists ──
Bela Nemeth
Cadet de l'espace
Grobert
Julius Aston
Koral Banko
Max Swan
Nebula Somni
Sigimund
Sub-City Keys
Tomasz Kraal
Tonie Green
Volta Celeste

# ── SlopTracker.org (Suno/Udio AI, 2025-2026) ──
19s Soulers
Abel Abaddon
Ash Reed
Aventhis
Backroad Raised
Black River Whiskey
Breaking Rust
Broken Trails
Cain Walker
Caleb Raines
Colter Rayne
Damon Price
Doc Raven
Domus Made
Drew Meadows
Eli Creed
Enlly
Enlly Blue
Frontier Heart
Georgia Phantom
JD Steel
Jerry's Sound Room
King Willonius
Lana Rosewood
Let Babylon Burn
Lone Star Lyric House
Mason Jar Moonshine
Morgan Luna
Nick Hustles
Nina Blaze
Nolan Graves
Orion7
Owen James
Red Village
Shifty Brent
Soul Blues Icon
Soul'd Out
Sons of Ashes
starletste_official
The Naughty Jukebox
The Soulful Gentlemen
True Roots Blues
Unbound Music
Vowless
Whiskey Circuit
ZionRay

# ── MBW 2025 AI investigation ──
Funkorama
Hyperdrive Sound
Stellar Cruise
Terry "Goldmind" Watkins
The Devil Inside
The Smoothies
The Velvet Sundown
Velvet Funk
What Is?

# ── Reddit / Slate / Whiskey Riff AI cover bands ──
Highway Outlaws
Saltwater Saddles
Terry & The Dustriders
Waterfront Wranglers

# ── Adam Faze investigation (2023) ──
Crash Tortoise
Isabelle Morninglocks
Queezpoor
The Brave Android
Viper Beelzebub

# ── Michael Smith streaming fraud (2024-2026) ──
Calm Baseball
Calm Connected
Calm Identity
Calm Knuckles
Calliope Bloom
Calliope Erratum
Zygotic Washstands

# ── Wargame-confirmed AI filler ──
Adriana Soulful
Calming River
Deep Ambient Moods
Elena Veil
Jade Amara
Luna Pearl
Serene Rainfall
Soul Kitchen Radio
Warm Breeze
White Noise Baby Sleep

# ── Known virtual/AI artists ──
FN Meka
Miquela
Ghostwriter
Sleepy John

# ── Sony Music / Yellowstone mood music ──
# (Sleepy John listed above)
```

- [ ] **Step 2: Create `ai_allowlist.txt`**

```text
# AI Allowlist — Music Discovery
# Artists listed here will NEVER be blocked by AI detection.
# Use this to override false positives from ai_blocklist.txt or the metadata heuristic.
# One artist name per line (case-insensitive). Blank lines and # comments are ignored.
```

- [ ] **Step 3: Commit**

```bash
git add ai_blocklist.txt ai_allowlist.txt
git commit -m "feat: add AI/fake artist blocklist and allowlist files"
```

---

### Task 2: Add `load_ai_blocklist()` and `load_ai_allowlist()` with Tests

**Files:**
- Modify: `music_discovery.py` (after `load_user_blocklist` at line ~676)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_music_discovery.py` after the existing `test_load_user_blocklist_*` tests (around line 1343):

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_music_discovery.py::test_load_ai_blocklist_reads_names tests/test_music_discovery.py::test_load_ai_blocklist_missing_file tests/test_music_discovery.py::test_load_ai_allowlist_reads_names tests/test_music_discovery.py::test_load_ai_allowlist_missing_file -v`
Expected: FAIL with `AttributeError: module 'music_discovery' has no attribute 'load_ai_blocklist'`

- [ ] **Step 3: Implement in `music_discovery.py`**

Add after `load_user_blocklist` (line ~676):

```python
def load_ai_blocklist(path):
    """Load AI/fake artist blocklist (plain text, same format as blocklist.txt).
    Returns a set of lowercase artist names."""
    return load_user_blocklist(path)

def load_ai_allowlist(path):
    """Load AI allowlist — artists that should never be blocked by AI detection.
    Returns a set of lowercase artist names."""
    return load_user_blocklist(path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_music_discovery.py::test_load_ai_blocklist_reads_names tests/test_music_discovery.py::test_load_ai_blocklist_missing_file tests/test_music_discovery.py::test_load_ai_allowlist_reads_names tests/test_music_discovery.py::test_load_ai_allowlist_missing_file -v`
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: add load_ai_blocklist() and load_ai_allowlist()"
```

---

### Task 3: Extend `fetch_filter_data()` to Extract Bio, Tags, and MB Type

**Files:**
- Modify: `music_discovery.py:690-744` (`fetch_filter_data`)
- Modify: `music_discovery.py:70` (add `MUSICBRAINZ_SEARCH_URL` constant)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write failing tests**

Add after the existing `test_fetch_filter_data_*` tests (around line 575):

```python
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
    """When Last.fm returns no MBID, falls back to MusicBrainz name search."""
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
    # MusicBrainz search returns a match
    mb_search_resp = MagicMock()
    mb_search_resp.status_code = 200
    mb_search_resp.json.return_value = {
        "artists": [{
            "name": "Fake Band",
            "score": 100,
            "type": "Group",
            "releases": [{"title": "Album"}],
            "relations": [],
        }]
    }
    with patch("requests.get", side_effect=[search_resp, lastfm_resp, mb_search_resp]):
        result = md.fetch_filter_data("fake band", "fake_key")
    assert result["mb_type"] == "Group"
    assert result["mb_has_releases"] is True
    assert result["debut_year"] is None


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_music_discovery.py -k "test_fetch_filter_data_extracts_bio or test_fetch_filter_data_no_mbid_falls or test_fetch_filter_data_mb_search_rejects_low or test_fetch_filter_data_mb_search_rejects_name or test_fetch_filter_data_bio_strips" -v`
Expected: FAIL — new fields not returned by `fetch_filter_data()`

- [ ] **Step 3: Add `MUSICBRAINZ_SEARCH_URL` constant**

In `music_discovery.py`, after the existing `MUSICBRAINZ_API_URL` line (line 70):

```python
MUSICBRAINZ_SEARCH_URL = "https://musicbrainz.org/ws/2/artist/"
```

- [ ] **Step 4: Add `_clean_bio_length()` helper**

In `music_discovery.py`, before `fetch_filter_data()` (around line 688):

```python
import re as _re

def _clean_bio_length(bio_content):
    """Return length of bio content after stripping HTML and Last.fm boilerplate."""
    if not bio_content:
        return 0
    # Strip HTML tags
    text = _re.sub(r"<[^>]+>", "", bio_content)
    # Strip Last.fm boilerplate suffix
    text = _re.sub(r"\s*Read more on Last\.fm\.?\s*$", "", text, flags=_re.IGNORECASE)
    return len(text.strip())
```

Note: `import re as _re` — check if `re` is already imported at the top of the file. If so, use the existing import name instead.

- [ ] **Step 5: Extend `fetch_filter_data()` implementation**

Replace the body of `fetch_filter_data()` in `music_discovery.py` (lines 690-744) with:

```python
def fetch_filter_data(artist, api_key):
    """Fetch Last.fm listener count, bio/tags, and MusicBrainz debut year/type for an artist.
    Uses artist.search first to resolve the canonical name, then artist.getInfo
    for the MBID/bio/tags, then MusicBrainz for debut year and type.
    Returns {"listeners": int, "debut_year": int|None, "bio_length": int,
             "tag_count": int, "mb_type": str|None, "mb_has_releases": bool},
    or {} on any failure.
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

        # Step 2: get listener count, MBID, bio, and tags via getInfo
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
        bio_content = data.get("bio", {}).get("content", "")
        bio_length  = _clean_bio_length(bio_content)
        tag_count   = len(data.get("tags", {}).get("tag", []))

        # Step 3: get debut year and type from MusicBrainz
        debut_year = None
        mb_type = None
        mb_has_releases = False

        if mbid:
            # Direct MBID lookup (existing path)
            mb_resp = requests.get(
                MUSICBRAINZ_API_URL.format(mbid),
                timeout=10,
                headers={"User-Agent": MB_USER_AGENT},
                params={"fmt": "json", "inc": "releases"},
            )
            if mb_resp.status_code == 200:
                mb_data = mb_resp.json()
                begin = (mb_data.get("life-span", {}).get("begin") or "").strip()
                if begin:
                    debut_year = int(begin[:4])
                mb_type = mb_data.get("type")
                mb_has_releases = len(mb_data.get("releases", [])) > 0
        else:
            # Fallback: MusicBrainz name search
            mb_search_resp = requests.get(
                MUSICBRAINZ_SEARCH_URL,
                timeout=10,
                headers={"User-Agent": MB_USER_AGENT},
                params={"query": f'artist:"{artist}"', "fmt": "json", "limit": 1},
            )
            if mb_search_resp.status_code == 200:
                artists = mb_search_resp.json().get("artists", [])
                if artists:
                    top = artists[0]
                    score = top.get("score", 0)
                    mb_name = top.get("name", "")
                    if score >= 80 and mb_name.strip().lower() == artist.strip().lower():
                        mb_type = top.get("type")
                        mb_has_releases = len(top.get("releases", [])) > 0
                        begin = (top.get("life-span", {}).get("begin") or "").strip()
                        if begin:
                            debut_year = int(begin[:4])

        return {
            "listeners": listeners,
            "debut_year": debut_year,
            "bio_length": bio_length,
            "tag_count": tag_count,
            "mb_type": mb_type,
            "mb_has_releases": mb_has_releases,
        }
    except Exception as e:
        log.debug(f"fetch_filter_data failed for '{artist}': {e}")
        return {}
```

- [ ] **Step 6: Run new tests to verify they pass**

Run: `python3 -m pytest tests/test_music_discovery.py -k "test_fetch_filter_data_extracts_bio or test_fetch_filter_data_no_mbid_falls or test_fetch_filter_data_mb_search_rejects_low or test_fetch_filter_data_mb_search_rejects_name or test_fetch_filter_data_bio_strips" -v`
Expected: 5 PASSED

- [ ] **Step 7: Run ALL existing `fetch_filter_data` tests**

Run: `python3 -m pytest tests/test_music_discovery.py -k "test_fetch_filter_data" -v`

Some existing tests may fail because they don't include the new fields in their mock responses. Update each failing test's MusicBrainz mock to include `"type"` and `"releases"` fields, and Last.fm mock to include `"bio"` and `"tags"` fields. Also update assertions to check the new fields are present.

For example, `test_fetch_filter_data_returns_listeners_and_debut` (line 406) needs its `mb_resp` mock updated:
```python
mb_resp.json.return_value = {
    "life-span": {"begin": "1985-01-01"},
    "type": "Group",
    "releases": [{"title": "OK Computer"}],
}
```
And its `lastfm_resp` mock needs bio/tags:
```python
lastfm_resp.json.return_value = {
    "artist": {
        "stats": {"listeners": "5800000"},
        "mbid": "a74b1b7f-71a5-4011-9441-d0b5e4122711",
        "bio": {"content": "Radiohead are an English rock band formed in 1985."},
        "tags": {"tag": [{"name": "rock"}]},
    }
}
```
And assertions expanded:
```python
assert result["bio_length"] > 0
assert result["tag_count"] == 1
assert result["mb_type"] == "Group"
assert result["mb_has_releases"] is True
```

Apply similar updates to: `test_fetch_filter_data_missing_mbid`, `test_fetch_filter_data_lastfm_failure`, `test_fetch_filter_data_network_error`, `test_fetch_filter_data_year_only_begin`, `test_fetch_filter_data_uses_search_for_canonical_name`, `test_fetch_filter_data_falls_back_when_search_empty`, `test_fetch_filter_data_falls_back_when_search_fails`, `test_fetch_filter_data_both_calls_fail`.

- [ ] **Step 8: Run full test suite to verify no regressions**

Run: `python3 -m pytest tests/test_music_discovery.py -v`
Expected: ALL PASSED

- [ ] **Step 9: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: extend fetch_filter_data() with bio, tags, MB type for AI detection"
```

---

### Task 4: Implement `check_ai_artist()` with Tests

**Files:**
- Modify: `music_discovery.py` (after `load_ai_allowlist`)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_music_discovery.py`:

```python
# ── check_ai_artist ───────────────────────────────────────

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
    entry = {"ai_check": "pass", "ai_check_date": "2026-03-30"}
    blocked, reason = md.check_ai_artist("some artist", entry, AI_BL, set())
    assert blocked is False
    assert reason == "pass"

def test_check_ai_artist_cache_hit_whitelisted():
    """Cached whitelisted_mb is returned."""
    entry = {"ai_check": "whitelisted_mb", "ai_check_date": "2026-03-30"}
    blocked, reason = md.check_ai_artist("real band", entry, AI_BL, set())
    assert blocked is False
    assert reason == "whitelisted_mb"

def test_check_ai_artist_cache_blocked_metadata_expired():
    """Expired blocked_metadata (>90 days) is re-evaluated."""
    entry = {
        "ai_check": "blocked_metadata", "ai_check_date": "2025-12-01",
        "listeners": 500, "bio_length": 0, "tag_count": 0,
        "mb_type": None, "mb_has_releases": False,
    }
    blocked, reason = md.check_ai_artist("old block", entry, set(), set())
    # Re-evaluated: still meets block criteria
    assert blocked is True
    assert reason == "blocked_metadata"

def test_check_ai_artist_cache_blocked_metadata_fresh():
    """Fresh blocked_metadata (<90 days) is returned from cache."""
    entry = {
        "ai_check": "blocked_metadata", "ai_check_date": "2026-03-15",
    }
    blocked, reason = md.check_ai_artist("recent block", entry, set(), set())
    assert blocked is True
    assert reason == "blocked_metadata"

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_music_discovery.py -k "test_check_ai_artist" -v`
Expected: FAIL with `AttributeError: module 'music_discovery' has no attribute 'check_ai_artist'`

- [ ] **Step 3: Implement `check_ai_artist()`**

Add to `music_discovery.py` after `load_ai_allowlist()`:

```python
import datetime as _datetime

# Whitelist MB types that indicate a real artist
_MB_WHITELIST_TYPES = {"Person", "Group", "Orchestra", "Choir"}
_AI_CACHE_TTL_DAYS = 90

def check_ai_artist(name, filter_entry, ai_blocklist, ai_allowlist):
    """Three-layer AI artist detection.

    Evaluation order (short-circuits):
      1. Allowlist → pass
      2. Static blocklist → block
      3. Cache → return cached result (if fresh)
      4. MusicBrainz type (Person/Group/Orchestra/Choir with releases) → whitelist
      5. Last.fm heuristic (no bio + no tags + <1000 listeners) → block
      6. API failure (empty entry) → pass (benefit of doubt)
      7. Default → pass

    Args:
        name: lowercase artist name
        filter_entry: dict from filter_cache (may be empty on API failure)
        ai_blocklist: set of lowercase names from ai_blocklist.txt
        ai_allowlist: set of lowercase names from ai_allowlist.txt

    Returns:
        (blocked: bool, reason: str)
    Side effect:
        Updates filter_entry with ai_check and ai_check_date fields.
    """
    # Step 1: Allowlist
    if name in ai_allowlist:
        return False, "allowlist"

    # Step 2: Static blocklist (always checked, overrides cache)
    if name in ai_blocklist:
        return True, "blocked_static"

    # Step 3: Cache
    cached = filter_entry.get("ai_check")
    if cached:
        if cached == "blocked_metadata":
            # Check TTL
            check_date = filter_entry.get("ai_check_date", "")
            if check_date:
                try:
                    age = (_datetime.date.today()
                           - _datetime.date.fromisoformat(check_date))
                    if age.days < _AI_CACHE_TTL_DAYS:
                        return True, "blocked_metadata"
                except ValueError:
                    pass
                # Expired — fall through to re-evaluate
            else:
                # No date — fall through to re-evaluate
                pass
        else:
            # pass or whitelisted_mb — return as-is
            return (False, cached)

    # Step 4: MusicBrainz type whitelist
    # Empty entry means API failure — skip to step 6
    if not filter_entry:
        return False, "pass"

    mb_type = filter_entry.get("mb_type")
    mb_has_releases = filter_entry.get("mb_has_releases", False)
    if mb_type in _MB_WHITELIST_TYPES and mb_has_releases:
        filter_entry["ai_check"] = "whitelisted_mb"
        filter_entry["ai_check_date"] = _datetime.date.today().isoformat()
        return False, "whitelisted_mb"

    # Step 5: Last.fm metadata heuristic
    listeners = filter_entry.get("listeners")
    if listeners is None:
        # No listener data despite non-empty entry — inconclusive, pass
        return False, "pass"

    bio_length = filter_entry.get("bio_length", 0)
    tag_count = filter_entry.get("tag_count", 0)

    if listeners < 1000 and bio_length < 50 and tag_count == 0:
        filter_entry["ai_check"] = "blocked_metadata"
        filter_entry["ai_check_date"] = _datetime.date.today().isoformat()
        return True, "blocked_metadata"

    # Step 7: Default pass
    filter_entry["ai_check"] = "pass"
    filter_entry["ai_check_date"] = _datetime.date.today().isoformat()
    return False, "pass"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_music_discovery.py -k "test_check_ai_artist" -v`
Expected: ALL PASSED

- [ ] **Step 5: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: implement check_ai_artist() three-layer detection"
```

---

### Task 5: Extend `filter_candidates()` with Rule 4 and Logging

**Files:**
- Modify: `music_discovery.py:1289-1313` (`filter_candidates`)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_music_discovery.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_music_discovery.py -k "test_filter_candidates_blocks_ai or test_filter_candidates_ai_allowlist or test_filter_candidates_no_ai_args" -v`
Expected: FAIL — `filter_candidates` doesn't accept `ai_blocklist`/`ai_allowlist` kwargs

- [ ] **Step 3: Extend `filter_candidates()`**

Replace the function in `music_discovery.py`:

```python
def filter_candidates(scored, filter_cache, file_blocklist=frozenset(),
                      ai_blocklist=None, ai_allowlist=None):
    """Remove candidates that are well-known artists the user likely already knows,
    or that are detected as AI-generated/fake.
    Exclusion rules (any one is sufficient):
      1. Name is in ARTIST_BLOCKLIST (hardcoded) or file_blocklist (auto-detected).
      2. Name matches a decade/era pattern (e.g. "70s", "80's music").
      3. listeners > POPULAR_THRESHOLD AND debut_year <= CLASSIC_YEAR.
      4. AI detection: check_ai_artist() (static blocklist + MB type + Last.fm heuristic).
    scored: list of (score, name) tuples.
    filter_cache: {artist: {"listeners": int, ...}} dict.
    file_blocklist: set of lowercase names from blocklist_cache.json.
    ai_blocklist: set of lowercase names from ai_blocklist.txt (or None to skip Rule 4).
    ai_allowlist: set of lowercase names from ai_allowlist.txt (or None)."""
    combined = ARTIST_BLOCKLIST | file_blocklist
    result = []
    counts = {"blocklist": 0, "decade": 0, "popularity": 0,
              "ai_static": 0, "ai_metadata": 0}
    for score, name in scored:
        if name in combined:
            counts["blocklist"] += 1
            log.debug(f"Filtered: {name} (blocklist)")
            continue
        if _DECADE_RE.match(name):
            counts["decade"] += 1
            log.debug(f"Filtered: {name} (decade pattern)")
            continue
        data       = filter_cache.get(name, {})
        listeners  = data.get("listeners")
        debut_year = data.get("debut_year")
        if (listeners is not None and listeners > POPULAR_THRESHOLD
                and debut_year is not None and debut_year <= CLASSIC_YEAR):
            counts["popularity"] += 1
            log.debug(f"Filtered: {name} (popular classic: {listeners} listeners, debut {debut_year})")
            continue
        # Rule 4: AI detection (only if ai_blocklist was provided)
        if ai_blocklist is not None:
            blocked, reason = check_ai_artist(
                name, data, ai_blocklist, ai_allowlist or set())
            if blocked:
                if reason == "blocked_static":
                    counts["ai_static"] += 1
                else:
                    counts["ai_metadata"] += 1
                log.debug(f"Filtered: {name} (AI: {reason})")
                continue
        result.append((score, name))
    total_removed = len(scored) - len(result)
    if total_removed > 0:
        log.info(f"Filtered {len(scored)} → {len(result)} candidates: "
                 f"{counts['blocklist']} blocklist, {counts['decade']} decade, "
                 f"{counts['popularity']} popularity, {counts['ai_static']} AI-static, "
                 f"{counts['ai_metadata']} AI-metadata")
    return result
```

- [ ] **Step 4: Run new tests**

Run: `python3 -m pytest tests/test_music_discovery.py -k "test_filter_candidates" -v`
Expected: ALL PASSED (new and existing)

- [ ] **Step 5: Run full test suite**

Run: `python3 -m pytest tests/ -x -q`
Expected: ALL PASSED

- [ ] **Step 6: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: add AI detection Rule 4 to filter_candidates() with logging"
```

---

### Task 6: Thread AI Detection Through `signal_analysis.py` and `signal_experiment.py`

**Files:**
- Modify: `signal_analysis.py:20-32` (`_run_scoring`)
- Modify: `signal_experiment.py:598-603` (loading), `signal_experiment.py:309-319` (`run_experiment`), `signal_experiment.py:774-777` (call site)
- Test: `tests/test_signal_analysis.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_signal_analysis.py`:

```python
def test_run_scoring_passes_ai_blocklist_to_filter(monkeypatch):
    """ai_blocklist and ai_allowlist are forwarded to filter_candidates."""
    from signal_analysis import _run_scoring

    captured = {}
    def mock_filter(scored, fc, file_blocklist=frozenset(),
                    ai_blocklist=None, ai_allowlist=None):
        captured["ai_blocklist"] = ai_blocklist
        captured["ai_allowlist"] = ai_allowlist
        return scored

    monkeypatch.setattr("music_discovery.filter_candidates", mock_filter)

    cache = {"seed": {"candidate": 0.5}}
    signals = {
        "favorites": {"seed": 10},
        "playcount": {}, "playlists": {}, "ratings": {},
        "heavy_rotation": {}, "recommendations": {},
    }
    from signal_scoring import DEFAULT_WEIGHTS
    _run_scoring(cache, signals, DEFAULT_WEIGHTS,
                 filter_cache={"candidate": {}},
                 ai_blocklist={"elena veil"},
                 ai_allowlist={"mayhem"})
    assert captured["ai_blocklist"] == {"elena veil"}
    assert captured["ai_allowlist"] == {"mayhem"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_signal_analysis.py::test_run_scoring_passes_ai_blocklist_to_filter -v`
Expected: FAIL — `_run_scoring` doesn't accept/forward `ai_blocklist`

- [ ] **Step 3: Update `_run_scoring()` in `signal_analysis.py`**

Replace lines 20-32:

```python
def _run_scoring(cache, signals, weights, **kwargs):
    """Convenience wrapper for scoring with given weights.

    If filter_cache and file_blocklist are in kwargs, applies
    filter_candidates after scoring to remove well-known artists.
    Also forwards ai_blocklist and ai_allowlist for AI detection.
    """
    filter_cache = kwargs.pop("filter_cache", None)
    file_blocklist = kwargs.pop("file_blocklist", frozenset())
    ai_blocklist = kwargs.pop("ai_blocklist", None)
    ai_allowlist = kwargs.pop("ai_allowlist", None)
    ranked = score_candidates_multisignal(cache, signals, weights, **kwargs)
    if filter_cache is not None:
        from music_discovery import filter_candidates
        ranked = filter_candidates(ranked, filter_cache, file_blocklist,
                                   ai_blocklist=ai_blocklist,
                                   ai_allowlist=ai_allowlist)
    return ranked
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_signal_analysis.py::test_run_scoring_passes_ai_blocklist_to_filter -v`
Expected: PASS

- [ ] **Step 5: Update `signal_experiment.py` to load and thread AI blocklist/allowlist**

In `signal_experiment.py`, after the `file_blocklist` loading (around line 601), add:

```python
    ai_blocklist = load_ai_blocklist(
        pathlib.Path(__file__).parent / "ai_blocklist.txt")
    ai_allowlist = load_ai_allowlist(
        pathlib.Path(__file__).parent / "ai_allowlist.txt")
```

Update the import at the top of `signal_experiment.py` to include the new functions. Find the existing import from `music_discovery` and add `load_ai_blocklist, load_ai_allowlist`:

```python
from music_discovery import (
    ...,
    load_ai_blocklist, load_ai_allowlist,
)
```

Update `eval_exclude` (line 603) to include `ai_blocklist`:

```python
    eval_exclude = library_artists | user_blocklist | file_blocklist | ai_blocklist
```

Update `scoring_kwargs` in `run_experiment()` call (around line 777) to include AI args:

```python
    report, phase_a, phase_d = run_experiment(
        signals, scrape_cache, apple_cache, rejected_cache,
        user_blocklist, top_n=args.top_n,
        filter_cache=filter_cache, file_blocklist=file_blocklist,
        ai_blocklist=ai_blocklist, ai_allowlist=ai_allowlist)
```

Update `run_experiment()` signature and `scoring_kwargs` dict (around line 309):

```python
def run_experiment(signals, scrape_cache, apple_cache, rejected_cache,
                   user_blocklist, top_n=TOP_N,
                   filter_cache=None, file_blocklist=frozenset(),
                   ai_blocklist=None, ai_allowlist=None):
    """Run all four analysis phases and generate the report."""
    scoring_kwargs = {
        "apple_cache": apple_cache,
        "apple_weight": 0.2,
        "blocklist_cache": rejected_cache,
        "user_blocklist": user_blocklist,
        "filter_cache": filter_cache,
        "file_blocklist": file_blocklist,
        "ai_blocklist": ai_blocklist,
        "ai_allowlist": ai_allowlist,
    }
```

- [ ] **Step 6: Run all signal analysis and signal experiment tests**

Run: `python3 -m pytest tests/test_signal_analysis.py tests/test_signal_experiment.py -v`
Expected: ALL PASSED

- [ ] **Step 7: Run full test suite**

Run: `python3 -m pytest tests/ -x -q`
Expected: ALL PASSED

- [ ] **Step 8: Commit**

```bash
git add signal_analysis.py signal_experiment.py music_discovery.py tests/test_signal_analysis.py
git commit -m "feat: thread AI blocklist/allowlist through signal analysis pipeline"
```

---

### Task 7: Collision Audit of Static Blocklist

**Files:**
- Modify: `ai_blocklist.txt`

- [ ] **Step 1: Write and run audit script**

Write a temporary script that checks each name in `ai_blocklist.txt` against MusicBrainz for real-artist collisions. For each name, query MusicBrainz search and check if a result with score >= 80, exact name match, and type Person/Group has releases. Flag any matches.

```python
import requests, time, pathlib

blocklist = pathlib.Path("ai_blocklist.txt")
names = []
for line in blocklist.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#"):
        names.append(line)

collisions = []
for i, name in enumerate(names, 1):
    print(f"[{i}/{len(names)}] Checking: {name}")
    resp = requests.get(
        "https://musicbrainz.org/ws/2/artist/",
        headers={"User-Agent": "MusicDiscoveryTool/1.0 (https://github.com/networkingguru/music-discovery)"},
        params={"query": f'artist:"{name}"', "fmt": "json", "limit": 1},
        timeout=10,
    )
    if resp.status_code == 200:
        artists = resp.json().get("artists", [])
        if artists:
            top = artists[0]
            if (top.get("score", 0) >= 80
                    and top.get("name", "").strip().lower() == name.strip().lower()
                    and top.get("type") in ("Person", "Group", "Orchestra", "Choir")
                    and len(top.get("releases", [])) > 0):
                collisions.append((name, top["type"], top.get("score")))
                print(f"  *** COLLISION: {top['type']}, score={top['score']}")
    time.sleep(1.1)

print(f"\n=== {len(collisions)} collisions found ===")
for name, typ, score in collisions:
    print(f"  {name} ({typ}, score={score})")
```

Run: `python3 /tmp/audit_ai_blocklist.py`

- [ ] **Step 2: Remove colliding names from `ai_blocklist.txt`**

For each collision found, either remove the name or add it to `ai_allowlist.txt` if the AI artist is more prominent than the real one. Document removals in the collision audit comment at the top of the file.

- [ ] **Step 3: Commit**

```bash
git add ai_blocklist.txt ai_allowlist.txt
git commit -m "fix: remove collision-risk entries from AI blocklist after audit"
```

---

### Task 8: Integration Test — End-to-End Verification

**Files:**
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write integration test**

Add to `tests/test_music_discovery.py`:

```python
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
```

- [ ] **Step 2: Run integration test**

Run: `python3 -m pytest tests/test_music_discovery.py::test_ai_detection_end_to_end -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `python3 -m pytest tests/ -x -q`
Expected: ALL PASSED

- [ ] **Step 4: Commit**

```bash
git add tests/test_music_discovery.py
git commit -m "test: add end-to-end integration test for AI artist detection"
```

---

### Task 9: Update `main()` in `music_discovery.py` to Load AI Lists

**Files:**
- Modify: `music_discovery.py` (in `main()`, around line 1440-1450)

- [ ] **Step 1: Find the blocklist loading in `main()`**

Look for where `user_blocklist` and `file_blocklist` are loaded in `main()`. Add AI blocklist/allowlist loading alongside them and pass to `filter_candidates()` calls.

In `music_discovery.py` `main()`, find the block around line 1442:

```python
    user_blocklist = load_user_blocklist(
        pathlib.Path(__file__).parent / "blocklist.txt")
```

Add after it:

```python
    ai_blocklist = load_ai_blocklist(
        pathlib.Path(__file__).parent / "ai_blocklist.txt")
    ai_allowlist = load_ai_allowlist(
        pathlib.Path(__file__).parent / "ai_allowlist.txt")
```

- [ ] **Step 2: Thread through to `filter_candidates()` calls in `main()`**

Find all calls to `filter_candidates()` in `main()` and add `ai_blocklist=ai_blocklist, ai_allowlist=ai_allowlist` kwargs. There should be one or more calls — search for `filter_candidates(` in the function.

- [ ] **Step 3: Run full test suite**

Run: `python3 -m pytest tests/ -x -q`
Expected: ALL PASSED

- [ ] **Step 4: Commit**

```bash
git add music_discovery.py
git commit -m "feat: load AI blocklist/allowlist in music_discovery main()"
```

---

### Task 10: Final Verification

- [ ] **Step 1: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: ALL PASSED, no warnings about missing imports or unused variables

- [ ] **Step 2: Verify blocklist file loads correctly**

```bash
python3 -c "
from music_discovery import load_ai_blocklist, load_ai_allowlist
bl = load_ai_blocklist('ai_blocklist.txt')
al = load_ai_allowlist('ai_allowlist.txt')
print(f'AI blocklist: {len(bl)} entries')
print(f'AI allowlist: {len(al)} entries')
# Spot-check a few entries
assert 'elena veil' in bl
assert 'deep watch' in bl
assert 'mayhem' not in bl  # collision-removed
print('All checks passed.')
"
```

- [ ] **Step 3: Dry-run check_ai_artist against known examples**

```bash
python3 -c "
from music_discovery import load_ai_blocklist, load_ai_allowlist, check_ai_artist

bl = load_ai_blocklist('ai_blocklist.txt')
al = load_ai_allowlist('ai_allowlist.txt')

# Static blocklist hit
blocked, reason = check_ai_artist('elena veil', {}, bl, al)
assert blocked and reason == 'blocked_static', f'Expected blocked_static, got {reason}'

# Real band with MB Group
entry = {'mb_type': 'Group', 'mb_has_releases': True, 'listeners': 5000, 'bio_length': 200, 'tag_count': 3}
blocked, reason = check_ai_artist('real band', entry, bl, al)
assert not blocked and reason == 'whitelisted_mb', f'Expected whitelisted_mb, got {reason}'

# AI filler (no MB, no bio, no tags, low listeners)
entry = {'listeners': 10, 'bio_length': 0, 'tag_count': 0, 'mb_type': None, 'mb_has_releases': False}
blocked, reason = check_ai_artist('ai filler', entry, bl, al)
assert blocked and reason == 'blocked_metadata', f'Expected blocked_metadata, got {reason}'

# API failure (empty entry) → benefit of doubt
blocked, reason = check_ai_artist('unknown', {}, bl, al)
assert not blocked and reason == 'pass', f'Expected pass, got {reason}'

print('All AI detection checks passed.')
"
```

- [ ] **Step 4: Commit final state**

```bash
git add -A
git commit -m "feat: AI artist detection complete — static blocklist, MB type, Last.fm heuristic"
```
