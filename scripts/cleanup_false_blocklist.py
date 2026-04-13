#!/usr/bin/env python3
"""One-time cleanup: remove false-positive entries from blocklist_cache.json
and search_strikes.json caused by the artist normalization gap (issue #18)."""

import json
import pathlib

CACHE_DIR = pathlib.Path.home() / ".cache" / "music_discovery"

FALSE_POSITIVES = [
    "mister mister",
    "jimi hendrix and the experience",
    "bob seger and the silver bullet band",
    "hall and oates",
    "cars",
    "pretenders",
    "terence trent d\u00b4arby",
    "reo speed wagon",
    "reo speedwagon",
]

def cleanup_blocklist():
    path = CACHE_DIR / "blocklist_cache.json"
    if not path.exists():
        print(f"  {path} not found, skipping.")
        return
    with open(path) as f:
        data = json.load(f)
    blocked = data.get("blocked", [])
    original_count = len(blocked)
    blocked = [a for a in blocked if a.lower() not in {fp.lower() for fp in FALSE_POSITIVES}]
    removed = original_count - len(blocked)
    data["blocked"] = blocked
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  blocklist_cache.json: removed {removed} entries ({original_count} -> {len(blocked)})")

def cleanup_strikes():
    path = CACHE_DIR / "search_strikes.json"
    if not path.exists():
        print(f"  {path} not found, skipping.")
        return
    with open(path) as f:
        data = json.load(f)
    strikes = data.get("strikes", {})
    original_count = len(strikes)
    fp_set = {fp.lower() for fp in FALSE_POSITIVES}
    strikes = {k: v for k, v in strikes.items() if k.lower() not in fp_set}
    removed = original_count - len(strikes)
    data["strikes"] = strikes
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  search_strikes.json: removed {removed} entries ({original_count} -> {len(strikes)})")

if __name__ == "__main__":
    print("Cleaning up false-positive blocklist/strike entries (issue #18)...")
    cleanup_blocklist()
    cleanup_strikes()
    print("Done.")
