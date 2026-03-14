# The Clever Bits

The non-obvious engineering challenges behind Music Discovery — for anyone curious about what made this harder than it looks.

## 1. Proximity-Based Scoring from a Visual Map
music-map.com renders similar artists as a spatial cloud with no API. The Playwright scraper extracts actual pixel coordinates from the rendered page, computes Euclidean distance from the viewport center, and converts that to a 0–1 proximity score. The lightweight requests fallback uses DOM link order as a proxy. This turns a visual UI — designed for humans to browse — into quantitative similarity data.

## 2. The Three-Layer Playlist Pipeline
There is no Apple Music API that lets you search for a song and add it to a playlist. The solution chains three completely different systems: the iTunes Search API (find the store track ID — free, no key needed), the macOS MediaPlayer framework via JavaScript for Automation (play the track to make it appear in Music.app's scope), and AppleScript (grab the now-playing track and add it to the playlist). Each layer exists because the one before it can't finish the job alone.

## 3. Stale Playback Detection
The original playlist builder played a track, waited 3 seconds, then grabbed "current track" from Music.app and added it to the playlist. But sometimes the previous track was still playing when the grab happened, resulting in duplicates. The fix: snapshot whatever is playing before starting playback, then poll every 0.5 seconds until the current track changes (up to 5 seconds). Simple in hindsight, but the symptom — wrong songs appearing in the playlist — took real debugging to trace back to a timing race.

## 4. The Monster Playlist
A bug in playlist setup caused tracks to accumulate instead of being replaced across runs. After several test runs, the playlist had thousands of tracks. Attempting to clear it via AppleScript caused Music.app to beachball indefinitely (it tries to delete tracks one by one). The fix: check the track count before clearing. If it's over 500, delete the entire playlist object and create a fresh one. This is faster and doesn't lock up the app.

## 5. Auto-Blocklist Detection
music-map.com doesn't just return artist names. It sometimes returns song titles ("Let Her Go"), genre labels ("Classic Rock"), decade tags ("80s"), and other noise. These look like artists in the raw data. The auto-detection system flags any scored candidate that returns empty results ({}) from Last.fm — meaning Last.fm has never heard of them as an artist. Combined with regex filters for decade patterns and cover-song tags, this catches most noise without requiring manual curation per user.

## 6. Log-Weighted Scoring
A user who has loved 200 tracks by one artist and 3 tracks by another shouldn't get recommendations dominated by the first artist. The scoring formula uses log(loved_count + 1) as a weight, which compresses the gap: 200 loved tracks gives about 3.7x the weight of 3 loved tracks, not 67x. This means your deep obsessions still matter more, but your casual likes contribute meaningfully.

## 7. Hardware-Seeded API Key Encryption
Storing a plaintext API key in a .env file felt wrong. The solution: XOR the key against a SHA-256 hash of the machine's hardware UUID (IOPlatformUUID on macOS, MachineGuid on Windows, /etc/machine-id on Linux). It's not bank-grade cryptography, but the key is useless if the .env file is copied to another machine. Falls back to plaintext gracefully if no hardware ID is available.

## 8. Scraper Auto-Detection
music-map.com's anti-scraping measures change unpredictably. Sometimes a simple HTTP request gets the full page; sometimes it returns a skeleton that needs JavaScript rendering. The script tests Plan A (lightweight requests) against a known artist ("radiohead") at startup. If it gets fewer than 3 results, it silently switches to Plan B (headless Chromium via Playwright). Users never need to know or configure which scraper is running.
