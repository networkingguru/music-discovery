# Music Discovery

Discover new music based on the artists you already love.

This tool reads your Apple Music library, finds similar artists via [music-map.com](https://www.music-map.com/), and scores them by proximity. An **adaptive engine** learns from your listening feedback each round, reweighting its scoring model so recommendations improve over time. Playlists mix new artist discovery with deep cuts from artists you already know.

> **Note:** This public repository is frozen as of April 2026. A new closed-source project with the latest version of the adaptive engine is under active development and will be released separately. See [Project Status](#project-status) below.

## Introduction by the Designer (NetworkingGuru)

<figure>
  <img src="./screenshot.png" alt="First run results">
  <figcaption><em>First run results. Small sample size, but out of the top 15 tracks, I loved 7 of them.</em></figcaption>
</figure>

So I've been searching for a decent music recommender since the 90's, and have yet to find one that is right more than 10% of the time. Perhaps I am weird and I know I have eclectic taste, but I also thought the existing algos probably sucked. 

Years ago, I found music-map, and was **immediately** struck by the idea that this is how recommendations should be done: Find what the user likes, figure out what is related to that, and offer it. But to maximize relevance, I thought an approach where you took ALL of the user's favorite artists and correlated them all, you should get a nice sorted list of possibles. 

Anyway, this seemed like a task right at the edge of my programming abilities, so I never got around to it. But then came Claude Code.

To learn Claude Code, I decided to vibe code this shit, but since I DO know Python, I did it in Python, in the hopes I could at least prevent the worst disasters. Still not sure how that worked, because I haven't done a lot of looking through the code. But I can tell you, with *absolute* certainty, that it was MUCH more difficult than I thought. And that fact has caused me to re-evaluate my stance on AI.

Claude is fucking amazing. 

See, this fucking thing had more obstacles than anything I have ever seen. At one point, between trying to brute force the Music API and hex editing a database, Claude had music playing through my laptop and was actively walking all of the buttons (through accessibility? Who fucking knows, this shit is WILD man) trying to figure out how to add a goddamn song to a playlist that it couldn't even SEE. I ended up with a playlist containing 1.3 million files and Claude briefly taking over my TV to my unending amusement and the consternation of my wife. This tool is unstoppable. 

Now, a few warnings before I end, because despite everything you see in this repo, I haven't written **anything** except this intro. So all code, docs, etc., are all by Claude. Now, I can code, and I can code in Python, and I'm decent at both. But no one should use the --playlist function without a full backup and a priest. Don't get me wrong: **IT FUCKING WORKS**, at least on my Mac. But this is the part of the script that had my Mac acting like the antagonist of the Exorcist. It made a 1.3 **MILLION** entry playlist that BROKE APPLE MUSIC. It's fucking evil, but it's also awesome. And it works, but don't use it. You have been warned, no refunds, shirt and shoes required, God be with ye.

## Quick Start

```bash
git clone https://github.com/networkingguru/music-discovery.git
cd music-discovery
pip install -r requirements.txt
playwright install chromium
```

### Adaptive Engine (recommended)

The adaptive engine is a feedback loop that learns your taste over multiple rounds. Workflow: **seed → build → listen → feedback → repeat**.

```bash
# 1. Seed: collect library signals and build the initial model
python adaptive_engine.py --seed

# 2. Build: score candidates and create an Apple Music playlist
python adaptive_engine.py --build

# 3. Listen to the playlist in Apple Music. Favorite what you like.
#    Then process your listening behavior:
python adaptive_engine.py --feedback

# Repeat steps 2-3. The model retrains each round.
```

### One-shot mode

If you just want a single discovery run without the feedback loop:

```bash
python music_discovery.py
```

## Requirements

- **Python 3.14+** for the adaptive engine (compiled modules require CPython 3.14). The one-shot mode works with Python 3.9+.
- **macOS** for the adaptive engine (uses JXA to read Music.app directly). The one-shot mode also works on Windows with an XML library export.
- **Apple Music library** with some listening history (favorites, play counts, playlists, and ratings are all used as signals — the more data, the better the recommendations)
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
| Adaptive engine | Yes | No |
| One-shot discovery | Yes | Yes |
| Last.fm filtering | Yes | Yes |
| Playlist building | Yes (native) | Yes (XML import, one-shot only) |

## How It Works

The original one-shot mode scrapes music-map.com for similar artists and scores them by proximity to your library. The adaptive engine adds a logistic regression model and affinity graph that retrain after each feedback round, combining new artist discovery with deep cuts from artists you already know. See [Technical Overview](docs/how-it-works.md) for the full pipeline, scoring algorithm, and architecture.

## Compiled Modules

The adaptive discovery engine — the core algorithm that learns your taste and improves recommendations over time — is distributed as compiled native libraries (`.so` files) rather than Python source code. This includes:

- `adaptive_engine` — orchestration, two-channel scoring, cooldown logic
- `weight_learner` — logistic regression model training and inference
- `affinity_graph` — similarity graph with BFS signal propagation
- `feedback` — listening session snapshot diffing and aggregation
- `signal_scoring` — multi-signal composite scoring

**These modules work identically to their source versions.** Python imports them transparently — no code changes are needed. They are compiled with Cython into native machine code.

### Why?

Every major streaming service — Apple Music, Spotify, YouTube Music, Amazon Music, Tidal — has billions of dollars, massive engineering teams, and access to the listening data of hundreds of millions of users. And yet their recommendation algorithms are, to put it charitably, not great. This project's adaptive engine produces better recommendations from a single user's library than these companies manage with all their resources.

The core algorithm is the result of significant R&D, and distributing it as readable source code would be an open invitation for any company to absorb the approach into their own systems without attribution or compensation. Compiling these modules protects that work while still allowing anyone to:

- **Use the tool** exactly as intended
- **Read and learn from** all the surrounding infrastructure (scraping, filtering, playlist building, signal collection, analysis tools)
- **Modify the open-source components** to suit their needs

A new closed-source project with the latest version of the adaptive engine will be released separately. See [Project Status](#project-status) below.

## Project Status

**This repository is frozen as of April 2026.** It represents the public, open-source release of Music Discovery with the adaptive engine distributed as compiled binaries.

A successor project is under active, closed-source development with:
- The latest version of the adaptive engine
- New features and signal sources
- Multi-platform support
- A proper GUI

When the new project is ready for release, it will be announced here. Watch this repo or follow [@networkingguru](https://github.com/networkingguru) for updates.

## Documentation

- [User Guide](docs/user-guide.md) — installation, first run, configuration, troubleshooting
- [Technical Overview](docs/how-it-works.md) — how the scoring, filtering, and playlist systems work
- [Clever Bits](docs/clever-bits.md) — the non-obvious engineering challenges
- [Changelog](CHANGELOG.md) — milestones and notable incidents

## License

This project uses a split license:

- **Open-source components** (all `.py` files) are licensed under the [GNU Affero General Public License v3.0](LICENSE) with a commercial licensing option. See [NOTICE](NOTICE) for details.
- **Compiled engine modules** (all `.so` files) are proprietary. See [ENGINE-LICENSE](ENGINE-LICENSE) for terms.
