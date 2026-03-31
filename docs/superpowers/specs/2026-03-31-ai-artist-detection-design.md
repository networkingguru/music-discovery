# AI Artist Detection Design

## Problem

AI-generated and fake artists pollute discovery playlists. The iTunes/Apple Music search API doesn't distinguish between real and AI artists, so fake artists that score well in the signal pipeline end up in evaluation playlists.

## Solution

Three-layer detection integrated into `filter_candidates()` as Rule 4.

### Layer 1: Static Blocklist (`ai_blocklist.txt`)

A curated list of ~153 known fake/AI artists sourced from:
- MBW "Original 50" fake artists (Quiz & Larossi pseudonyms, 2017)
- Johan Rohr / Firefly Entertainment / Chillmi pseudonyms (Dagens Nyheter 2022, MBW 2024)
- MBW Epidemic Sound / PFC-adjacent ghost artists
- SlopTracker.org curated AI artists (Suno/Udio generated, 2025-2026)
- MBW 2025 AI investigation
- Reddit/Slate/Whiskey Riff AI cover bands
- Adam Faze investigation (Document Journal 2023)
- Michael Smith streaming fraud case (court documents, 2024-2026)
- Wargame-confirmed AI filler artists (Adriana Soulful, Elena Veil, etc.)
- Known virtual/AI artists (FN Meka, Miquela, Nora Van Elken, Ghostwriter)

Format: plain text, one artist per line, `#` comments. Same format as `blocklist.txt`.

Exclusion: "Mayhem" removed due to collision with real Norwegian black metal band.

### Layer 2: MusicBrainz Lookup

Query MusicBrainz artist search API. If the artist is found with `type = "Group"`, whitelist immediately (skip Layer 3). Rationale: wargaming showed 0% of AI artists are listed as groups vs 67% of real indie artists.

- Endpoint: `https://musicbrainz.org/ws/2/artist/?query=artist:{name}&fmt=json`
- User-Agent: `MusicDiscoveryTool/1.0 (https://github.com/networkingguru/music-discovery)`
- Rate limit: 1 second between requests (MusicBrainz requirement)

### Layer 3: Last.fm Fallback

If MusicBrainz returns no result, check Last.fm `artist.getInfo` (already called by `fetch_filter_data()`). Block if ALL of:
- No bio (empty or missing)
- No tags (empty or missing)
- Listeners < 1,000

Rationale: wargaming showed real artists almost always have some community-generated metadata. Requiring all three conditions minimizes false positives against genuinely obscure artists.

## Caching

Add `ai_check` field to each artist's entry in `filter_cache.json`:

```json
{"listeners": 5000, "debut_year": 2018, "ai_check": "pass"}
```

Values:
- `"pass"` — cleared by metadata check
- `"blocked_static"` — matched static blocklist
- `"blocked_metadata"` — failed Layer 2+3 metadata check
- `"whitelisted_group"` — MusicBrainz confirmed as Group

Cached results are reused across runs. Only uncached artists trigger API calls.

## Integration Points

### `music_discovery.py`

1. **New function: `load_ai_blocklist(path)`** — loads `ai_blocklist.txt`, returns lowercase set. Same pattern as `load_user_blocklist()`.

2. **New function: `check_ai_artist(name, filter_cache, ai_blocklist, api_key)`** — runs the three-layer check, returns `(blocked: bool, reason: str)`. Updates `filter_cache` entry with `ai_check` field.

3. **Extended: `fetch_filter_data()`** — also extract bio text and tags from the existing Last.fm `artist.getInfo` response. Store in filter_cache as `"bio_length"` and `"tag_count"`.

4. **Extended: `filter_candidates()`** — add Rule 4 after existing rules: call `check_ai_artist()` for any artist not already filtered.

### `signal_experiment.py`

- Load `ai_blocklist` in `main()` alongside `user_blocklist` and `file_blocklist`
- Pass through to filtering via `eval_exclude` or directly to `filter_candidates()`

### New file: `ai_blocklist.txt`

~153 entries, organized by source category with `#` comments.

## Thresholds

| Check | Condition | Action |
|-------|-----------|--------|
| Static blocklist | Exact case-insensitive match | Block |
| MusicBrainz type = "Group" | Found with group type | Pass (whitelist) |
| Metadata heuristic | MB not found AND Last.fm listeners < 1,000 AND no bio AND no tags | Block |
| Default | None of the above triggered | Pass |

## Performance

- Static blocklist: O(1) set lookup, no API calls
- MusicBrainz: 1 API call, 1s rate limit. Short-circuits Layer 3 on Group match.
- Last.fm: No extra call — extends existing `fetch_filter_data()` response parsing
- All results cached — subsequent runs skip API calls for known artists
