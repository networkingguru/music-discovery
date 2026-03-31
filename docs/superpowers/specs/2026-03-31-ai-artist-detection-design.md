# AI Artist Detection Design

## Problem

AI-generated and fake artists pollute discovery playlists. The iTunes/Apple Music search API doesn't distinguish between real and AI artists, so fake artists that score well in the signal pipeline end up in evaluation playlists.

## Solution

Three-layer detection integrated into `filter_candidates()` as Rule 4, plus static blocklist added to `eval_exclude` for the playlist-building path.

### Layer 1: Static Blocklist (`ai_blocklist.txt`)

A curated list of known fake/AI artists sourced from:
- MBW "Original 50" fake artists (Quiz & Larossi pseudonyms, 2017)
- Johan Rohr / Firefly Entertainment / Chillmi pseudonyms (Dagens Nyheter 2022, MBW 2024)
- MBW Epidemic Sound / PFC-adjacent ghost artists
- SlopTracker.org curated AI artists (Suno/Udio generated, 2025-2026)
- MBW 2025 AI investigation
- Reddit/Slate/Whiskey Riff AI cover bands
- Adam Faze investigation (Document Journal 2023)
- Michael Smith streaming fraud case (court documents, 2024-2026)
- Wargame-confirmed AI filler artists (Adriana Soulful, Elena Veil, etc.)
- Known virtual/AI artists (FN Meka, Miquela, Ghostwriter)

Format: plain text, one artist per line, `#` comments. Same format as `blocklist.txt`.

**Collision audit required:** Before shipping, every entry must be checked against MusicBrainz, Discogs, and Spotify for real-artist collisions. The following names are known collision risks and must be removed or verified:
- "Mayhem" — real Norwegian black metal band (removed)
- "Aven" — real electronic producer (272K Spotify listeners) (removed)
- "Nora Van Elken" — likely real anonymous Dutch electronic producer (removed pending investigation)
- "DV8" — real Australian blues-rock band (removed)
- "David Allen" — real musicians (Gang of Four bassist, etc.) (removed)
- "Owen James" — real UK guitarist/composer (removed)
- "Shea" — real R&B singer (removed)
- "Hermann" — real French DJ-producer (removed)
- "Fellows" — real band on Spotify (removed)
- "Callous" — real metal/punk bands (removed)

General rule: any single common word, common first name, or common two-word name combination must be excluded from the static list unless the AI artist is the dominant result on streaming platforms.

Layer 1 is **always checked regardless of cache state** — a cached `ai_check: "pass"` does not override a later addition to the static blocklist.

### Layer 2: MusicBrainz Lookup

Extract `type` from the MusicBrainz response already fetched by `fetch_filter_data()`. If the artist has an MBID (from Last.fm), the existing MBID-based lookup at `musicbrainz.org/ws/2/artist/{mbid}` already returns the `type` field — no additional API call needed.

If no MBID is available, fall back to MusicBrainz artist search:
- Endpoint: `https://musicbrainz.org/ws/2/artist/?query=artist:"{name}"&fmt=json` (quotes required for multi-word names)
- User-Agent: `MusicDiscoveryTool/1.0 (https://github.com/networkingguru/music-discovery)`
- Rate limit: 1 second between requests (MusicBrainz requirement)
- Match criteria: result `name` must be an exact case-insensitive match to the queried name. Score must be >= 80. Partial/fuzzy matches are treated as "not found."

**Whitelist types:** If MusicBrainz returns type = Person, Group, Orchestra, or Choir, whitelist (skip Layer 3). These types all indicate a real artist. Only "Character" and "Other" are ambiguous.

**Whitelist requires substance:** A MusicBrainz entry with just a name and type but no linked releases, relationships, or tags does not qualify for whitelisting. At least one linked release or relationship is required.

Cached as `ai_check: "whitelisted_mb"` with the type stored.

### Layer 3: Last.fm Metadata Heuristic

If MusicBrainz returns no result (or an empty entry), check Last.fm `artist.getInfo` data (already fetched by `fetch_filter_data()`). Block if ALL of:
- No bio: bio `content` field is empty/missing OR fewer than 50 characters after stripping HTML and the standard Last.fm suffix ("Read more on Last.fm...")
- No tags: zero entries in the `tags.tag` array
- Listeners < 1,000

**Requires successful API response:** If `fetch_filter_data()` returned `{}` (transient failure), Layer 3 returns "pass" (benefit of the doubt). The heuristic only applies when we have actual data confirming thin metadata.

Rationale: wargaming showed real artists almost always have some community-generated metadata. Requiring all three conditions minimizes false positives against genuinely obscure artists.

## User Override: `ai_allowlist.txt`

A plain-text file (same format as `blocklist.txt`) where the user can list artists that should never be blocked by AI detection. Checked before all three layers — if an artist is in the allowlist, AI detection is skipped entirely.

This provides a clean escape hatch for false positives without requiring manual cache edits.

## Caching

Add fields to each artist's entry in `filter_cache.json`:

```json
{"listeners": 5000, "debut_year": 2018, "bio_length": 342, "tag_count": 5, "mb_type": "Group", "ai_check": "pass"}
```

`ai_check` values:
- `"pass"` — cleared by metadata check
- `"blocked_static"` — matched static blocklist (not cached — always re-checked)
- `"blocked_metadata"` — failed Layer 2+3 metadata check
- `"whitelisted_mb"` — MusicBrainz confirmed as Person/Group/Orchestra/Choir with substance

**Cache behavior:**
- Layer 1 (static blocklist) is always checked, ignoring cache. This ensures new blocklist additions take effect immediately.
- Layers 2+3 use the cache. If `ai_check` is present, skip API calls.
- `blocked_metadata` entries expire after 90 days (re-checked on next run). New artists may gain MusicBrainz/Last.fm presence over time.
- `pass` and `whitelisted_mb` entries do not expire.

## Logging

`filter_candidates()` currently filters silently. Add logging:
- `DEBUG` level: log each exclusion with the rule that triggered it (e.g., "AI-blocked: Elena Veil (static blocklist)")
- `INFO` level: summary after filtering (e.g., "Filtered 312 → 287 candidates: 8 blocklist, 3 decade, 9 popularity, 5 AI-static, 2 AI-metadata")

## Integration Points

### `music_discovery.py`

1. **New function: `load_ai_blocklist(path)`** — loads `ai_blocklist.txt`, returns lowercase set. Same pattern as `load_user_blocklist()`.

2. **New function: `load_ai_allowlist(path)`** — loads `ai_allowlist.txt`, returns lowercase set.

3. **New function: `check_ai_artist(name, filter_entry, ai_blocklist, ai_allowlist)`** — runs the three-layer check using data already in `filter_entry` (from `fetch_filter_data()`). Returns `(blocked: bool, reason: str)`. No API calls — all data comes from the cache entry.

4. **Extended: `fetch_filter_data()`** — also extract from the existing responses:
   - From Last.fm `artist.getInfo`: `bio_length` (len of bio content after stripping HTML/boilerplate), `tag_count` (len of tags array)
   - From MusicBrainz MBID lookup (already done for debut_year): `mb_type` (Person/Group/etc), `mb_has_releases` (bool)
   - For artists without MBID: fall back to MusicBrainz name search (new API call, 1s rate limit, exact match + score >= 80 required)

5. **Extended: `filter_candidates()`** — add Rule 4 after existing rules. Add logging for all rules (not just Rule 4).

### `signal_experiment.py`

- Load `ai_blocklist` in `main()` alongside `user_blocklist` and `file_blocklist`
- Add `ai_blocklist` to `eval_exclude` set — this ensures `build_stratified_artist_list()` (which uses `eval_exclude` for set-based filtering, not `filter_candidates()`) also excludes static-blocklisted AI artists
- Pass `ai_blocklist` and `ai_allowlist` through to `filter_candidates()` for the scoring path

### New files

- `ai_blocklist.txt` — curated list of known AI/fake artists (collision-audited)
- `ai_allowlist.txt` — user overrides (starts empty, with a comment explaining its purpose)

## Thresholds

| Check | Condition | Action |
|-------|-----------|--------|
| Allowlist | In `ai_allowlist.txt` | Pass (skip all checks) |
| Static blocklist | In `ai_blocklist.txt` (case-insensitive, always checked) | Block |
| MusicBrainz type | Person, Group, Orchestra, or Choir with ≥1 release/relationship | Pass (whitelist) |
| Metadata heuristic | MB not found AND Last.fm listeners < 1,000 AND bio < 50 chars AND 0 tags | Block |
| API failure | `fetch_filter_data()` returned `{}` | Pass (benefit of doubt) |
| Default | None of the above triggered | Pass |

## Performance

- Static blocklist + allowlist: O(1) set lookups, no API calls
- MusicBrainz: **No additional API call** for artists with MBID (type extracted from existing `fetch_filter_data()` response). One new search call only for artists without MBID, subject to 1s rate limit.
- Last.fm: No extra call — extends existing `fetch_filter_data()` response parsing to also grab bio and tags
- All results cached with 90-day TTL on `blocked_metadata` — subsequent runs skip API calls for known artists
- Progress logging during MusicBrainz searches so long runs show activity
