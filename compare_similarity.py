#!/usr/bin/env python3
"""
Apple Music API vs music-map.com — Similar Artists Comparison POC

Fetches similar artists from both Apple Music API and music-map.com for a
random sample of artists from the user's library, then prints a formatted
comparison report showing overlap and differences.

Usage:
    python compare_similarity.py
    python compare_similarity.py --count 5
    python compare_similarity.py --artists "Radiohead,Bjork,Portishead"

Requires:
    - Apple Music API credentials in .env (see .env.example)
    - A .p8 private key file from Apple Developer portal
"""

import argparse
import json
import os
import pathlib
import random
import sys
import time

import jwt
import requests

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from music_discovery import (
    load_dotenv,
    _resolve_library_path,
    parse_library,
    detect_scraper,
)

APPLE_MUSIC_BASE = "https://api.music.apple.com/v1/catalog"
STOREFRONT = "us"
TOKEN_TTL = 3600
API_RATE_LIMIT = 0.5
SAMPLE_SIZE = 12


def generate_apple_music_token(key_id, team_id, key_path):
    """Generate a JWT developer token for Apple Music API."""
    if not key_id or not team_id:
        raise ValueError("APPLE_MUSIC_KEY_ID and APPLE_MUSIC_TEAM_ID must be set in .env")
    key_file = pathlib.Path(key_path).expanduser().resolve()
    if not key_file.exists():
        raise FileNotFoundError(f"Apple Music private key not found: {key_file}")
    with open(key_file, "r") as f:
        private_key = f.read()
    now = int(time.time())
    payload = {"iss": team_id, "iat": now, "exp": now + TOKEN_TTL}
    headers = {"alg": "ES256", "kid": key_id}
    return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)


class AppleMusicClient:
    """Minimal client for Apple Music catalog API."""

    def __init__(self, token):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
        self.base_url = f"{APPLE_MUSIC_BASE}/{STOREFRONT}"

    def search_artist(self, name):
        """Search for an artist by name. Returns (artist_id, matched_name) or (None, None)."""
        url = f"{self.base_url}/search"
        params = {"term": name, "types": "artists", "limit": 5}
        try:
            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  [API ERROR] Search failed for '{name}': {e}")
            return None, None
        data = resp.json()
        items = data.get("results", {}).get("artists", {}).get("data", [])
        if not items:
            return None, None
        name_lower = name.strip().lower()
        for item in items:
            api_name = item.get("attributes", {}).get("name", "")
            if api_name.strip().lower() == name_lower:
                return item["id"], api_name
        first = items[0]
        return first["id"], first.get("attributes", {}).get("name", name)

    def get_similar_artists(self, artist_id):
        """Fetch similar artists for a given Apple Music artist ID."""
        url = f"{self.base_url}/artists/{artist_id}"
        params = {"views": "similar-artists"}
        try:
            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  [API ERROR] Similar artists failed for ID {artist_id}: {e}")
            return []
        data = resp.json()
        views = data.get("data", [{}])[0].get("views", {})
        similar_view = views.get("similar-artists", {})
        similar_data = similar_view.get("data", [])
        results = []
        for item in similar_data:
            attrs = item.get("attributes", {})
            results.append({"name": attrs.get("name", "Unknown"), "id": item.get("id", "")})
        return results


def compare_for_artist(artist_name, apple_client, scrape_fn):
    """Fetch similar artists from both sources and return comparison data."""
    result = {
        "artist": artist_name, "apple_id": None, "apple_matched_name": None,
        "apple_similar": [], "musicmap_similar": {},
        "overlap": [], "apple_only": [], "musicmap_only": [],
    }
    print(f"  Fetching music-map.com data...")
    musicmap_data = scrape_fn(artist_name)
    result["musicmap_similar"] = musicmap_data
    time.sleep(0.5)

    print(f"  Searching Apple Music catalog...")
    artist_id, matched_name = apple_client.search_artist(artist_name)
    time.sleep(API_RATE_LIMIT)

    if artist_id is None:
        print(f"  [SKIP] Artist not found on Apple Music: '{artist_name}'")
        result["musicmap_only"] = list(musicmap_data.keys())
        return result

    result["apple_id"] = artist_id
    result["apple_matched_name"] = matched_name

    print(f"  Fetching Apple Music similar artists (ID: {artist_id})...")
    apple_similar = apple_client.get_similar_artists(artist_id)
    result["apple_similar"] = apple_similar
    time.sleep(API_RATE_LIMIT)

    apple_names = {a["name"].strip().lower() for a in apple_similar}
    musicmap_names = set(musicmap_data.keys())

    overlap = apple_names & musicmap_names
    result["overlap"] = sorted(overlap)
    result["apple_only"] = sorted(apple_names - musicmap_names)
    result["musicmap_only"] = sorted(musicmap_names - apple_names)
    return result


def print_report(results):
    """Print a formatted comparison report to stdout."""
    sep = "=" * 78
    thin_sep = "-" * 78
    print(f"\n{sep}")
    print(f"  APPLE MUSIC API vs MUSIC-MAP.COM — Similar Artists Comparison")
    print(f"{sep}\n")

    total_overlap = total_apple = total_musicmap = 0
    artists_with_apple_data = artists_with_musicmap_data = 0

    for r in results:
        print(f"\n{thin_sep}")
        artist_label = r["artist"]
        if r["apple_matched_name"] and r["apple_matched_name"].lower() != r["artist"].lower():
            artist_label += f"  (Apple: \"{r['apple_matched_name']}\")"
        print(f"  Artist: {artist_label}")
        if r["apple_id"]:
            print(f"  Apple Music ID: {r['apple_id']}")
        print(f"{thin_sep}")

        apple_count = len(r["apple_similar"])
        musicmap_count = len(r["musicmap_similar"])
        overlap_count = len(r["overlap"])

        if apple_count > 0: artists_with_apple_data += 1
        if musicmap_count > 0: artists_with_musicmap_data += 1
        total_apple += apple_count
        total_musicmap += musicmap_count
        total_overlap += overlap_count

        print(f"\n  Apple Music similar: {apple_count:>3}")
        print(f"  music-map.com similar: {musicmap_count:>3}")

        if apple_count == 0 and musicmap_count == 0:
            print(f"  [No similar artist data from either source]")
            continue

        if overlap_count > 0:
            pct_of_apple = (overlap_count / apple_count * 100) if apple_count else 0
            pct_of_musicmap = (overlap_count / musicmap_count * 100) if musicmap_count else 0
            print(f"  Overlap: {overlap_count:>3}  ({pct_of_apple:.0f}% of Apple, {pct_of_musicmap:.0f}% of music-map)")
            print(f"\n  Overlapping artists:")
            for name in r["overlap"]:
                mm_score = r["musicmap_similar"].get(name, 0)
                print(f"    {name:<40} (music-map proximity: {mm_score:.2f})")
        else:
            print(f"  Overlap: 0  (no shared artists)")

        if r["apple_only"]:
            print(f"\n  Apple Music only ({len(r['apple_only'])}):")
            for name in r["apple_only"][:15]:
                print(f"    {name}")
            if len(r["apple_only"]) > 15:
                print(f"    ... and {len(r['apple_only']) - 15} more")

        if r["musicmap_only"]:
            print(f"\n  music-map.com only ({len(r['musicmap_only'])}):")
            for name in r["musicmap_only"][:15]:
                score = r["musicmap_similar"].get(name, 0)
                print(f"    {name:<40} (proximity: {score:.2f})")
            if len(r["musicmap_only"]) > 15:
                print(f"    ... and {len(r['musicmap_only']) - 15} more")

    print(f"\n{sep}")
    print(f"  SUMMARY")
    print(f"{sep}")
    print(f"  Artists sampled:             {len(results)}")
    print(f"  Artists with Apple data:     {artists_with_apple_data}")
    print(f"  Artists with music-map data: {artists_with_musicmap_data}")
    print(f"  Total Apple similar:         {total_apple}")
    print(f"  Total music-map similar:     {total_musicmap}")
    print(f"  Total overlap:               {total_overlap}")
    if total_apple > 0:
        print(f"  Overlap as % of Apple:       {total_overlap / total_apple * 100:.1f}%")
    if total_musicmap > 0:
        print(f"  Overlap as % of music-map:   {total_overlap / total_musicmap * 100:.1f}%")
    print(f"{sep}\n")


def sample_library_artists(count):
    """Read the user's Music library and return a random sample of artist names."""
    library_path = _resolve_library_path()
    if library_path is None:
        print("ERROR: Could not find Music Library XML.")
        print("       Export it: Music.app -> File -> Library -> Export Library...")
        sys.exit(1)
    library_artists, _ = parse_library(library_path)
    if not library_artists:
        print("ERROR: No loved/favorited artists found in library.")
        sys.exit(1)
    sorted_artists = sorted(library_artists.items(), key=lambda x: x[1], reverse=True)
    top_half = sorted_artists[:max(len(sorted_artists) // 2, count)]
    sample = random.sample(top_half, min(count, len(top_half)))
    return [name for name, _ in sample]


def main():
    parser = argparse.ArgumentParser(description="Compare similar artists: Apple Music API vs music-map.com")
    parser.add_argument("--count", type=int, default=SAMPLE_SIZE, help=f"Number of random artists to compare (default: {SAMPLE_SIZE})")
    parser.add_argument("--artists", type=str, default=None, help="Comma-separated list of artist names (overrides --count)")
    args = parser.parse_args()

    load_dotenv()

    key_id = os.environ.get("APPLE_MUSIC_KEY_ID", "").strip()
    team_id = os.environ.get("APPLE_MUSIC_TEAM_ID", "").strip()
    key_path = os.environ.get("APPLE_MUSIC_KEY_PATH", "").strip()

    if not key_id or not team_id or not key_path:
        print("ERROR: Apple Music API credentials not configured.")
        print("       Set APPLE_MUSIC_KEY_ID, APPLE_MUSIC_TEAM_ID, and")
        print("       APPLE_MUSIC_KEY_PATH in your .env file.")
        print("       See .env.example for details.")
        sys.exit(1)

    print("Generating Apple Music API token...")
    try:
        token = generate_apple_music_token(key_id, team_id, key_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    print("Token generated successfully.")

    apple_client = AppleMusicClient(token)

    print("Detecting music-map.com scraper method...")
    scrape_fn = detect_scraper()

    if args.artists:
        artist_names = [a.strip().lower() for a in args.artists.split(",") if a.strip()]
        print(f"\nComparing {len(artist_names)} specified artists...")
    else:
        print(f"\nSampling {args.count} artists from your library...")
        artist_names = sample_library_artists(args.count)

    print(f"Artists: {', '.join(artist_names)}\n")

    results = []
    for i, artist in enumerate(artist_names, 1):
        print(f"\n[{i}/{len(artist_names)}] {artist}")
        result = compare_for_artist(artist, apple_client, scrape_fn)
        results.append(result)

    print_report(results)

    output_path = pathlib.Path(__file__).parent / "similarity_comparison.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Raw data saved to: {output_path}")


if __name__ == "__main__":
    main()
