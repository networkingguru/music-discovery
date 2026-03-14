# Music Discovery

Discover new music based on the artists you already love.

This tool reads artists from tracks you've marked as **Loved** or **Favorited** in your Apple Music (or iTunes) library, finds similar artists via [music-map.com](https://www.music-map.com/), scores them by proximity, and filters out well-known artists so only genuine discoveries appear. Optionally builds an Apple Music playlist with top tracks from your discoveries.

## Quick Start

```bash
git clone https://github.com/networkingguru/music-discovery.git
cd music-discovery
pip install -r requirements.txt
playwright install chromium
python music_discovery.py
```

## Requirements

- **Python 3.9+**
- **macOS or Windows**
- **Apple Music or iTunes library** exported as XML, with loved or favorited tracks (the tool discovers new artists based on artists you've loved — without any loved or favorited tracks, it has nothing to work with)
- **Last.fm API key** (optional, free) — improves results by filtering out well-known artists
- **Apple Music subscription** (recommended for playlist building) — without one, adding tracks to your library may purchase them individually instead of streaming. See the warning in Usage below.

## Usage

```bash
# Basic discovery
python music_discovery.py

# Specify a custom library path
python music_discovery.py --library ~/path/to/Library.xml

# Discovery + build an Apple Music playlist
python music_discovery.py --playlist
```

> **Important:** Playlist building adds tracks to your Apple Music library. Without an active Apple Music subscription, this may purchase individual tracks instead of streaming them. The author is not responsible for any charges incurred. Use at your own risk.

## Platform Notes

| Feature | macOS | Windows |
|---------|-------|---------|
| Artist discovery | Yes | Yes |
| Last.fm filtering | Yes | Yes |
| Playlist building | Yes (native) | Yes (XML import) |

## How It Works

See [Technical Overview](docs/how-it-works.md) for the full pipeline, scoring algorithm, and architecture.

## Documentation

- [User Guide](docs/user-guide.md) — installation, first run, configuration, troubleshooting
- [Technical Overview](docs/how-it-works.md) — how the scoring, filtering, and playlist systems work
- [Clever Bits](docs/clever-bits.md) — the non-obvious engineering challenges
- [Changelog](CHANGELOG.md) — milestones and notable incidents

## License

[MIT](LICENSE)
