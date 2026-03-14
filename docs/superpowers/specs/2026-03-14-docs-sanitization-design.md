# Documentation Sanitization & Distribution Readiness

**Date:** 2026-03-14
**Approach:** Docs-only pass first, code changes separate

---

## Overview

Prepare the Music Discovery documentation and code for public distribution. This covers two concerns:

1. **Documentation accuracy and safety** — fix incorrect URLs, remove references to unsupported platforms, add critical warnings about playlist risks, clarify how the tool works
2. **Code sanitization** — extract personal blocklist entries so the repo ships clean while preserving the user's local data

---

## Part 1: Documentation Changes

### README.md

| Change | Details |
|--------|---------|
| Remove Linux mentions | Drop Linux column from platform table, remove footnote, remove "(Linux users: specify library path with `--library`)" from requirements |
| Platform table | macOS and Windows only. Discovery: Yes/Yes. Last.fm filtering: Yes/Yes. Playlist building: Yes (native)/Yes (XML import) |
| Fix GitHub URL | Change `brianhill/music-discovery` to `networkingguru/music-discovery` in clone URL and any links |
| Update description | Mention the tool works from loved AND favorited tracks |
| Add loved/favorited to requirements | Note that an Apple Music library with loved or favorited tracks is required — the tool has nothing to work with without them |
| Apple Music subscription warning | Note that playlist building without an active Apple Music subscription may result in purchasing individual tracks instead of streaming them. Use at your own risk. |
| Keep Clever Bits link | Retain the Clever Bits entry in the Documentation section |

### CHANGELOG.md

| Change | Details |
|--------|---------|
| Monster playlist scale | Change "thousands of tracks" to "1.3 million tracks" |

**Note:** CHANGELOG entries for the blocklist extraction and Windows playlist support will be added when those code changes ship in Part 2, not during the docs-only pass.

### user-guide.md

| Change | Details |
|--------|---------|
| Fix GitHub URL | Change to `networkingguru/music-discovery` in all links, including the "Getting Help" section at the bottom |
| Loved/favorited requirement | Explain in Prerequisites that the tool identifies artists from tracks marked as Loved or Favorited. Without any loved or favorited tracks, the tool cannot function. |
| Beachball section | Add that you often must reboot your Mac to recover — Music.app may sit on "Loading Library" forever otherwise |
| Playlist warnings | Add prominent "Important" callouts: the playlist generator is complex and can cause Music.app to become unresponsive; an active Apple Music subscription is required — without one, the process may purchase individual tracks. The author is not responsible for any charges incurred. Use at your own risk. |
| Remove Linux mentions | Remove any remaining Linux references (default paths table is already macOS/Windows only) |

### how-it-works.md

| Change | Details |
|--------|---------|
| Layer 3 purchase warning | Add warning that `duplicate ct to source "Library"` may purchase the track without an active Apple Music subscription. Could be very costly across many tracks. |
| Oversized playlist clarification | Change wording to explicitly state: "if the existing **Music Discovery** playlist exceeds the cap, it is deleted and recreated from scratch. This check applies only to the Music Discovery playlist — no other playlists are affected." Use "exceeds" (strictly greater than 500, matching the code's `>` operator). |
| Remove Linux from UUID table | Drop the Linux row from Platform UUID sources |
| Windows playlist support | Update playlist building section to reflect Windows users can generate XML playlists via `--playlist` |

---

## Part 2: Code Changes

### Blocklist Extraction

**Goal:** Ship a clean repo without personal artist entries, while preserving them locally.

**Location:** `blocklist.txt` lives in the project root (next to `music_discovery.py`).

**File format:** One lowercase artist name per line. Blank lines and lines starting with `#` are ignored. Names are matched case-insensitively (lowercased on load), consistent with the hardcoded set.

**File is optional:** If `blocklist.txt` does not exist (e.g., fresh clone), it is silently ignored. The tool works fine without it.

**`.gitignore`:** Add `blocklist.txt` to `.gitignore`.

**What moves to `blocklist.txt`:**
All artist entries from the current `ARTIST_BLOCKLIST` — these are real artists with bad Last.fm data that are specific to individual users' libraries:
- "hall and oates", "cat stevens", "neil young & crazy horse", "jackson 5", "the jackson five", "bob seger and the silver bullet band", "pretenders", "eric burdon & war", "destinys child", "jimi hendrix and the experience"
- "cars", "reo speedwagon", "reo speed wagon", "emerson lake and palmer", "mister mister", "blondie", "ultravox", "uriah heep", "j. j. cale"
- "christina aguilera" (transient Last.fm API failure — a real artist, belongs in user-managed list)

**What stays hardcoded in `ARTIST_BLOCKLIST`:**
Non-artist entries that are universal false positives from music-map.com:
- "let her go", "say something", "riptide", "classic rock"

**Integration point:** The existing `load_blocklist()` function (line 483) already loads a file-based blocklist from a path and returns a set. A new function `load_user_blocklist()` will load from the project-root `blocklist.txt` using the same pattern, and its result will be merged into the `file_blocklist` set in `main()` alongside the existing auto-blocklist cache. The `filter_candidates()` call at line 1161 already accepts a `file_blocklist` parameter, so no changes to the filtering pipeline are needed.

**Three blocklist sources at filter time (unchanged interaction):**
1. `ARTIST_BLOCKLIST` (hardcoded) — universal non-artists, ships with code
2. `blocklist.txt` (new, `.gitignore`d, optional) — user's manual personal entries
3. `blocklist_cache.json` (existing, `~/.cache/`) — auto-detected non-artists at runtime

Auto-blocklist behavior is unchanged — new runtime detections still go to `blocklist_cache.json`.

### Windows `--playlist` XML Support

**Goal:** Let Windows users generate a playlist they can import into iTunes.

**Mechanism:**
- When `--playlist` is used on Windows, skip the AppleScript/MediaPlayer pipeline and go straight to XML export using existing `write_playlist_xml()` function
- Print a message with the XML file path and instructions to import in iTunes (File > Library > Import Playlist)
- Replace the macOS-only guard at line 1166 with a platform branch: macOS runs the full pipeline (unchanged), Windows runs XML-only export

**API key on Windows:** The Last.fm API key requirement is kept for Windows playlist building. The key is needed to fetch top tracks for discovered artists via `build_playlist()` → the top-tracks-fetching portion. Without it, there are no tracks to put in the XML. The existing gate at line 1169 (`elif not api_key`) remains and applies to both platforms.

**CHANGELOG:** A new entry will be added to CHANGELOG.md when this code change ships.

### GitHub URL in Code

**`MB_USER_AGENT` (line 75):** Update the hardcoded URL from `https://github.com/brianhill/music-discovery` to `https://github.com/networkingguru/music-discovery`.

---

## Out of Scope

- Changes to the auto-blocklist detection logic
- Changes to the scoring algorithm
- Changes to the scraping pipeline
- Threshold filter documentation inversion in how-it-works.md (Section 4, lines 65-68 describe it as a pass condition but the code treats it as an exclusion condition — this is a pre-existing doc bug, not part of this effort)
- Any new features beyond what's described above
