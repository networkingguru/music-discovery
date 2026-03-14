# Music Discovery — User Guide

Welcome! This guide walks you through setting up and using the Music Discovery script, which finds artists similar to ones you already love in your Apple Music or iTunes library.

---

## 1. Prerequisites

### Python 3.9 or newer

Download and install Python from [python.org/downloads](https://www.python.org/downloads/). During installation on Windows, check the box that says **"Add Python to PATH"**.

### Export your music library as XML

The script reads your library from an XML file you export from Music.app or iTunes.

**macOS (Music.app):**
1. Open Music.app
2. Go to **File → Library → Export Library...**
3. Save the file somewhere you'll remember

**Windows (iTunes):**
1. Open iTunes
2. Go to **File → Library → Export Library...**
3. Save the file somewhere you'll remember

### Default file locations

If you save the file to the default location, the script will find it automatically:

| Platform | Default path |
|----------|-------------|
| macOS | `~/Music/Music/Music Library.xml` |
| Windows | `~\Music\iTunes\iTunes Music Library.xml` |

If you saved it somewhere else, you can point the script to it using the `--library` flag (see Troubleshooting).

### Loved or Favorited tracks required

The script identifies your favorite artists by looking for tracks you have marked as **Loved** or **Favorited** in your library. If you don't have any loved or favorited tracks, the tool has nothing to work with and will produce no results.

To love a track in Music.app: right-click a song → **Love**. To favorite: click the star icon (if enabled).

---

## 2. Installation

Open a terminal (macOS: search for **Terminal** in Spotlight; Windows: open **Command Prompt**) and run these commands one at a time:

```bash
git clone https://github.com/networkingguru/music-discovery.git
cd music-discovery
pip install -r requirements.txt
playwright install chromium
```

The last command installs a browser component used to scrape artist similarity data. It only needs to be run once.

---

## 3. First Run

Start the script by running:

```bash
python music_discovery.py
```

### Last.fm API key prompt

On your very first run, the script will ask for a Last.fm API key. This key lets it filter out mainstream artists you've probably already heard of, so your results surface more interesting discoveries.

**To get a free key:**
1. Go to [last.fm/api/account/create](https://www.last.fm/api/account/create)
2. Sign in or create a free Last.fm account
3. Fill in the application form (name and description can be anything)
4. Copy the **API key** you receive

**You can also press Enter to skip.** The script will still work and find similar artists — you just won't have the mainstream-popularity filter applied, so some well-known names may appear in your results.

Once you enter a valid key, it is encrypted and saved to a `.env` file in the project folder. You won't be asked again.

### What happens during first run

- The script scrapes [music-map.com](https://music-map.com) to find artists similar to ones in your library
- It is rate-limited to one request per second to be respectful to the site
- Depending on the size of your library, **this can take a while** — sometimes 30 minutes or more for large libraries
- Results are cached, so subsequent runs are much faster

---

## 4. Understanding Your Results

Results are saved to:

```
~/.cache/music_discovery/music_discovery_results.txt
```

Open this file in any text editor. Each line shows a discovered artist and their score.

### What the score means

- **Higher score = stronger recommendation.** More artists in your library point to this discovery, and from closer proximity on the similarity map.
- Artists you have marked as **Loved** in your library carry extra weight, with diminishing returns (calculated via a logarithmic scale) so one mega-loved artist doesn't dominate everything.

### Filtering

Discovered artists are filtered out if they meet **both** of these conditions:

- More than 50,000 listeners on Last.fm (very mainstream), **and**
- Debuted before 2006 (long-established acts you've likely already encountered)

This keeps results focused on artists you're genuinely unlikely to know. If you skipped the API key, this filter is not applied.

---

## 5. Building a Playlist

> **Important — Please read before using `--playlist`:**
>
> The playlist generator is complex. It bridges three separate Apple APIs (iTunes Search, MediaPlayer, and AppleScript) and can cause Music.app to become unresponsive. See the Troubleshooting section for recovery steps if this happens.
>
> **An active Apple Music subscription is required.** Without one, the process may **purchase individual tracks** instead of streaming them. This could result in significant unexpected charges. The author is not responsible for any purchases incurred. **Use at your own risk.**

### macOS

On a Mac, the script automatically creates a playlist in Music.app:

```bash
python music_discovery.py --playlist
```

This will:

1. Take the top 50 discovered artists
2. Pull top tracks for each from your library (if you have them) or from iTunes Search
3. Create a playlist called **"Music Discovery"** in Music.app
4. Populate it with up to **500 tracks**

**A few things to expect:**
- You may hear brief audio playback during the process — this is normal. It's how tracks get added via AppleScript.
- The playlist is cleared and rebuilt from scratch each time you run with `--playlist`.
- Make sure Music.app is open before running.

### Windows

On Windows, the script generates an XML playlist file that you can import into iTunes:

```bash
python music_discovery.py --playlist
```

This will create a file at `~/.cache/music_discovery/Music Discovery.xml`. To use it:

1. Open iTunes
2. Go to **File → Library → Import Playlist...**
3. Select the generated XML file

---

## 6. Configuration

Advanced settings can be placed in a `.env` file in the project folder. The script creates this file automatically when you enter your API key, but you can edit it manually.

| Setting | Description |
|---------|-------------|
| `LASTFM_API_KEY` | Your Last.fm API key (stored encrypted automatically — don't edit by hand) |
| `CACHE_DIR` | Override the default cache location |
| `OUTPUT_DIR` | Override where results are written |

### Forcing a fresh scrape

The script caches similarity data so it doesn't re-scrape on every run. If you want completely fresh results (for example, after significantly changing your library), delete the cache files:

```
~/.cache/music_discovery/
```

You can delete the whole folder or individual `.json` files inside it. The script will rebuild the cache on the next run.

---

## 7. Troubleshooting

### "Library file not found"

The script couldn't find your XML export at the default location. Either:
- Export your library again (see Prerequisites above), or
- Point the script to your file manually:

```bash
python music_discovery.py --library "/path/to/your/Music Library.xml"
```

### Music.app beachballs (spinning wheel) during playlist build

This can happen if Music.app gets overloaded. **Force-quit Music.app** (right-click its Dock icon → Force Quit). You may need to **reboot your Mac** to recover — Music.app can get stuck on "Loading Library" indefinitely after a force-quit. Do not attempt to retry while it's unresponsive.

### "Playwright not installed" or browser errors

Run this command to install the required browser:

```bash
playwright install chromium
```

If that doesn't work, try:

```bash
python -m playwright install chromium
```

### Rate limit errors from music-map.com

The site may temporarily block requests if they come too fast. Wait a few minutes and run the script again. The cache means you won't lose progress — it will pick up where it left off.

### Results look wrong or stale

If your results seem outdated or don't reflect recent changes to your library, delete `filter_cache.json` from the cache folder:

```
~/.cache/music_discovery/filter_cache.json
```

Then re-run the script.

---

## Getting Help

If you run into an issue not covered here, check the project's GitHub page or open an issue at [github.com/networkingguru/music-discovery](https://github.com/networkingguru/music-discovery).
