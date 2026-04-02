#!/usr/bin/env python3
"""AI-generated artist detection wargaming via MusicBrainz + Last.fm APIs."""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

# Add project root to path so we can import the decrypt function
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from music_discovery import load_dotenv

# Load .env (handles ENC: decryption)
load_dotenv()

LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY", "")
if not LASTFM_API_KEY:
    print("ERROR: No LASTFM_API_KEY found in environment")
    sys.exit(1)

MB_USER_AGENT = "MusicDiscoveryTool/1.0 (https://github.com/networkingguru/music-discovery)"
MB_BASE = "https://musicbrainz.org/ws/2/artist/"
LFM_BASE = "http://ws.audioscrobbler.com/2.0/"

# --- Artist lists ---
AI_ARTISTS = [
    "Adriana Soulful",
    "Ashley Sienna",
    "Calming River",
    "Deep Ambient Moods",
    "Elena Veil",
    "Ghostwriter",
    "Jade Amara",
    "Luna Pearl",
    "Miquela",
    "Nora Van Elken",
    "Serene Rainfall",
    "Soul Kitchen Radio",
    "Warm Breeze",
    "White Noise Baby Sleep",
]

REAL_ARTISTS = [
    "Dreamgirl",
    "Dionaea",
    "Lila Lily",
    "Zuckerbaby",
    "Karmanjakah",
    "Psychework",
    "Ends with a Bullet",
    "Panzerballet",
    "Live My Last",
    "Hiss Golden Messenger",
    "TJ Helmerich",
    "The Korea",
    "Boy Golden",
    "Econoline Crush",
    "Dix Bruce",
]


def fetch_json(url, headers=None):
    """Fetch JSON from URL with optional headers."""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as e:
        return {"error": str(e)}


def query_musicbrainz(artist_name):
    """Query MusicBrainz for artist info."""
    params = urllib.parse.urlencode({"query": f'artist:"{artist_name}"', "fmt": "json", "limit": "1"})
    url = f"{MB_BASE}?{params}"
    data = fetch_json(url, headers={"User-Agent": MB_USER_AGENT})

    result = {
        "mb_found": False,
        "mb_score": 0,
        "mb_type": "",
        "mb_begin_date": "",
        "mb_area": "",
        "mb_tags": 0,
        "mb_disambiguation": "",
        "mb_members": False,
    }

    if "error" in data:
        result["mb_error"] = data["error"]
        return result

    artists = data.get("artists", [])
    if not artists:
        return result

    top = artists[0]
    score = top.get("score", 0)
    # Only consider it a real match if score >= 80
    if score < 80:
        return result

    result["mb_found"] = True
    result["mb_score"] = score
    result["mb_type"] = top.get("type", "")

    life_span = top.get("life-span", {})
    result["mb_begin_date"] = life_span.get("begin", "")

    area = top.get("area", {})
    result["mb_area"] = area.get("name", "") if area else ""

    tags = top.get("tags", [])
    result["mb_tags"] = len(tags)

    result["mb_disambiguation"] = top.get("disambiguation", "")

    # Check for group members via relations or type
    result["mb_members"] = top.get("type", "") == "Group"

    return result


def query_lastfm(artist_name):
    """Query Last.fm for artist info."""
    params = urllib.parse.urlencode({
        "method": "artist.getinfo",
        "artist": artist_name,
        "api_key": LASTFM_API_KEY,
        "format": "json",
    })
    url = f"{LFM_BASE}?{params}"
    data = fetch_json(url)

    result = {
        "lfm_found": False,
        "lfm_listeners": 0,
        "lfm_playcount": 0,
        "lfm_bio_len": 0,
        "lfm_tags": 0,
        "lfm_similar": 0,
        "lfm_has_mbid": False,
    }

    if "error" in data:
        result["lfm_error"] = data.get("message", str(data["error"]))
        return result

    artist = data.get("artist", {})
    if not artist:
        return result

    result["lfm_found"] = True

    stats = artist.get("stats", {})
    result["lfm_listeners"] = int(stats.get("listeners", 0))
    result["lfm_playcount"] = int(stats.get("playcount", 0))

    bio = artist.get("bio", {})
    content = bio.get("content", "")
    result["lfm_bio_len"] = len(content)

    tags = artist.get("tags", {}).get("tag", [])
    result["lfm_tags"] = len(tags) if isinstance(tags, list) else 0

    similar = artist.get("similar", {}).get("artist", [])
    result["lfm_similar"] = len(similar) if isinstance(similar, list) else 0

    result["lfm_has_mbid"] = bool(artist.get("mbid", ""))

    return result


def collect_all(artists, label):
    """Collect data for a list of artists."""
    results = []
    total = len(artists)
    for i, name in enumerate(artists):
        print(f"  [{label}] {i+1}/{total}: {name}...", end=" ", flush=True)

        mb = query_musicbrainz(name)
        time.sleep(1)

        lfm = query_lastfm(name)
        time.sleep(1)

        row = {"name": name, **mb, **lfm}
        results.append(row)
        print("done")

    return results


def print_table(results, label):
    """Print formatted results table."""
    print(f"\n{'='*120}")
    print(f"  {label}")
    print(f"{'='*120}")

    # Header
    fmt = "{:<25s} {:>5s} {:>5s} {:>8s} {:>6s} {:>5s} {:>8s} {:>8s} {:>5s} {:>5s} {:>5s} {:>4s}"
    print(fmt.format(
        "Artist", "MBfnd", "MBscr", "MBtype", "MBarea", "MBtag", "LFMlstn", "LFMplay", "LFMtg", "LFMsm", "MBID", "Bio"
    ))
    print("-" * 120)

    for r in results:
        print(fmt.format(
            r["name"][:25],
            "Y" if r["mb_found"] else "N",
            str(r["mb_score"]),
            r["mb_type"][:8] if r["mb_type"] else "-",
            r["mb_area"][:6] if r["mb_area"] else "-",
            str(r["mb_tags"]),
            str(r["lfm_listeners"]),
            str(r["lfm_playcount"]),
            str(r["lfm_tags"]),
            str(r["lfm_similar"]),
            "Y" if r.get("lfm_has_mbid") else "N",
            str(r["lfm_bio_len"])[:4],
        ))


def analyze(ai_results, real_results):
    """Analyze patterns that differentiate AI from real artists."""
    print(f"\n{'='*120}")
    print("  ANALYSIS")
    print(f"{'='*120}")

    def stats(results, key):
        vals = [r[key] for r in results]
        if not vals:
            return 0, 0, 0
        return min(vals), max(vals), sum(vals) / len(vals)

    def pct(results, key):
        if not results:
            return 0
        return sum(1 for r in results if r[key]) / len(results) * 100

    metrics = [
        ("MusicBrainz found", "mb_found", True),
        ("Has MBID on Last.fm", "lfm_has_mbid", True),
        ("MB type=Group (has members)", "mb_members", True),
    ]

    print(f"\n--- Boolean Signals ---")
    print(f"{'Signal':<35s} {'AI %':>8s} {'Real %':>8s} {'Delta':>8s}")
    print("-" * 65)
    for label, key, _ in metrics:
        ai_pct = pct(ai_results, key)
        real_pct = pct(real_results, key)
        print(f"{label:<35s} {ai_pct:>7.0f}% {real_pct:>7.0f}% {real_pct - ai_pct:>+7.0f}%")

    num_metrics = [
        ("Last.fm listeners", "lfm_listeners"),
        ("Last.fm playcount", "lfm_playcount"),
        ("Last.fm bio length", "lfm_bio_len"),
        ("Last.fm tags", "lfm_tags"),
        ("Last.fm similar artists", "lfm_similar"),
        ("MusicBrainz tags", "mb_tags"),
        ("MusicBrainz score", "mb_score"),
    ]

    print(f"\n--- Numeric Signals ---")
    print(f"{'Signal':<30s} {'AI min':>8s} {'AI avg':>8s} {'AI max':>8s} {'Real min':>8s} {'Real avg':>8s} {'Real max':>8s}")
    print("-" * 100)
    for label, key in num_metrics:
        ai_mn, ai_mx, ai_avg = stats(ai_results, key)
        r_mn, r_mx, r_avg = stats(real_results, key)
        print(f"{label:<30s} {ai_mn:>8.0f} {ai_avg:>8.0f} {ai_mx:>8.0f} {r_mn:>8.0f} {r_avg:>8.0f} {r_mx:>8.0f}")

    # Composite scoring
    print(f"\n--- Composite AI Detection Score ---")
    print("Score = weighted sum of red flags (higher = more likely AI)")
    print()

    all_results = [(r, "AI") for r in ai_results] + [(r, "REAL") for r in real_results]

    print(f"{'Artist':<25s} {'Type':>4s} {'Score':>6s}  Flags")
    print("-" * 100)

    for r, typ in all_results:
        score = 0
        flags = []

        if not r["mb_found"]:
            score += 3
            flags.append("no_MB")
        if not r.get("lfm_has_mbid"):
            score += 2
            flags.append("no_MBID")
        if r["lfm_listeners"] == 0:
            score += 3
            flags.append("0_listeners")
        elif r["lfm_listeners"] < 1000:
            score += 1
            flags.append("low_listeners")
        if r["lfm_bio_len"] < 100:
            score += 2
            flags.append("no_bio")
        if r["lfm_similar"] == 0:
            score += 2
            flags.append("no_similar")
        if r["lfm_tags"] == 0:
            score += 1
            flags.append("no_lfm_tags")
        if r["mb_tags"] == 0 and r["mb_found"]:
            score += 1
            flags.append("no_mb_tags")
        if not r["mb_area"]:
            score += 1
            flags.append("no_area")
        if not r["mb_begin_date"]:
            score += 1
            flags.append("no_begin")

        marker = " <-- MISS" if (typ == "AI" and score < 5) or (typ == "REAL" and score >= 5) else ""
        print(f"{r['name']:<25s} {typ:>4s} {score:>6d}  {', '.join(flags)}{marker}")

    # Summary
    ai_scores = []
    real_scores = []
    for r, typ in all_results:
        score = 0
        if not r["mb_found"]: score += 3
        if not r.get("lfm_has_mbid"): score += 2
        if r["lfm_listeners"] == 0: score += 3
        elif r["lfm_listeners"] < 1000: score += 1
        if r["lfm_bio_len"] < 100: score += 2
        if r["lfm_similar"] == 0: score += 2
        if r["lfm_tags"] == 0: score += 1
        if r["mb_tags"] == 0 and r["mb_found"]: score += 1
        if not r["mb_area"]: score += 1
        if not r["mb_begin_date"]: score += 1
        if typ == "AI":
            ai_scores.append(score)
        else:
            real_scores.append(score)

    print(f"\n--- Threshold Analysis ---")
    for threshold in range(3, 10):
        ai_caught = sum(1 for s in ai_scores if s >= threshold)
        real_flagged = sum(1 for s in real_scores if s >= threshold)
        print(f"  Threshold >= {threshold}: AI caught={ai_caught}/{len(ai_scores)} ({ai_caught/len(ai_scores)*100:.0f}%), "
              f"Real false-positives={real_flagged}/{len(real_scores)} ({real_flagged/len(real_scores)*100:.0f}%)")


if __name__ == "__main__":
    print("AI-Generated Artist Detection Wargaming")
    print("=" * 50)
    print(f"Testing {len(AI_ARTISTS)} AI artists and {len(REAL_ARTISTS)} real artists\n")

    print("Collecting AI artist data...")
    ai_results = collect_all(AI_ARTISTS, "AI")

    print("\nCollecting real artist data...")
    real_results = collect_all(REAL_ARTISTS, "REAL")

    print_table(ai_results, "AI-GENERATED ARTISTS")
    print_table(real_results, "REAL INDIE/OBSCURE ARTISTS")

    analyze(ai_results, real_results)

    # Save raw data
    output = {
        "ai_artists": ai_results,
        "real_artists": real_results,
    }
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp_ai_detection_results.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nRaw data saved to {out_path}")
