#!/usr/bin/env python3
"""
scrape_rejected.py — Scrape music-map proximity data for rejected artists.

"Rejected artists" are those in blocklist_cache.json (auto-blocklisted during
discovery runs) but NOT in blocklist.txt (the user's manually curated list).
These are artists worth having proximity data for, so negative scoring can
penalise candidates that are too close to them.

Output: rejected_scrape_cache.json  (in CACHE_DIR, same as other caches)

Usage:
    python scrape_rejected.py [--dry-run]

Options:
    --dry-run   Print what would be scraped without making any network requests.
"""

import argparse
import logging
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from music_discovery import (
    _build_paths,
    load_cache,
    save_cache,
    load_blocklist,
    load_user_blocklist,
    detect_scraper,
    load_dotenv,
    RATE_LIMIT,
)

log = logging.getLogger("scrape_rejected")


def main():
    parser = argparse.ArgumentParser(
        description="Scrape music-map data for rejected (auto-blocklisted) artists."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print artists to be scraped without making network requests.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv()

    paths = _build_paths()
    user_blocklist_path = pathlib.Path(__file__).parent / "blocklist.txt"

    # 1. Load blocklists (read-only)
    file_blocklist = load_blocklist(paths["blocklist"])
    user_blocklist = load_user_blocklist(user_blocklist_path)

    print(f"File blocklist (blocklist_cache.json): {len(file_blocklist)} artists")
    print(f"User blocklist (blocklist.txt):         {len(user_blocklist)} artists")

    # 2. Compute rejected = auto-blocklisted but NOT user-curated
    rejected_artists = file_blocklist - user_blocklist
    print(f"Rejected artists (file - user):         {len(rejected_artists)} artists")

    if not rejected_artists:
        print("Nothing to scrape.")
        return

    # 3. Load existing rejected scrape cache (read-only until we write)
    cache_path = paths["rejected_scrape"]
    cache = load_cache(cache_path)
    print(f"Existing cache entries:                 {len(cache)}")

    # 4. Determine which artists still need scraping
    to_scrape = sorted(a for a in rejected_artists if a not in cache)
    print(f"Artists needing scrape:                 {len(to_scrape)}")

    if not to_scrape:
        print("All rejected artists already cached. Nothing to do.")
        return

    if args.dry_run:
        print("\n[dry-run] Would scrape:")
        for artist in to_scrape:
            print(f"  {artist}")
        return

    # 5. Detect scraper method once, then scrape each missing artist
    print("\nDetecting scraper method...")
    scraper = detect_scraper()

    total = len(to_scrape)
    for i, artist in enumerate(to_scrape, 1):
        print(f"  [{i}/{total}] Scraping: {artist} ...", end=" ", flush=True)
        try:
            result = scraper(artist)
            cache[artist] = result
            n = len(result) if isinstance(result, dict) else 0
            print(f"{n} similar artists")
        except Exception as exc:
            log.warning(f"failed ({exc})")
            cache[artist] = {}

        # 6. Save after every artist so progress survives interruption
        save_cache(cache, cache_path)

        if i < total:
            time.sleep(RATE_LIMIT)

    # 7. Summary
    scraped = sum(1 for a in to_scrape if cache.get(a))
    empty = sum(1 for a in to_scrape if not cache.get(a))
    print(f"\nDone. Scraped {scraped} artists ({empty} returned no results).")
    print(f"Cache saved to: {cache_path}")


if __name__ == "__main__":
    main()
