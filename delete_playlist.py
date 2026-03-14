#!/usr/bin/env python3
"""Delete the monster 'Music Discovery' playlist in batches to avoid beachballing Music.app."""

import subprocess
import time
import sys

PLAYLIST_NAME = "Music Discovery"
BATCH_SIZE = 5000
TIMEOUT_PER_BATCH = 120  # seconds


def run_applescript(script, timeout=60):
    """Run an AppleScript and return (success, output)."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        else:
            return False, result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"


def get_track_count():
    """Get current track count of the playlist."""
    script = f'''
        with timeout of 60 seconds
            tell application "Music"
                set pl to user playlist "{PLAYLIST_NAME}"
                return count of tracks of pl
            end tell
        end timeout
    '''
    ok, result = run_applescript(script, timeout=90)
    if ok:
        return int(result)
    else:
        return None


def delete_batch(batch_size):
    """Delete a batch of tracks from the beginning of the playlist."""
    script = f'''
        with timeout of {TIMEOUT_PER_BATCH} seconds
            tell application "Music"
                set pl to user playlist "{PLAYLIST_NAME}"
                set trackCount to count of tracks of pl
                if trackCount is 0 then return 0
                set batchEnd to {batch_size}
                if trackCount < batchEnd then set batchEnd to trackCount
                delete (tracks 1 thru batchEnd of pl)
                return batchEnd
            end tell
        end timeout
    '''
    return run_applescript(script, timeout=TIMEOUT_PER_BATCH + 30)


def delete_empty_playlist():
    """Delete the now-empty playlist."""
    script = f'''
        with timeout of 30 seconds
            tell application "Music"
                delete user playlist "{PLAYLIST_NAME}"
            end tell
        end timeout
    '''
    return run_applescript(script, timeout=60)


def main():
    print(f"=== Monster Playlist Deleter ===")
    print(f"Target: '{PLAYLIST_NAME}'")
    print(f"Batch size: {BATCH_SIZE}")
    print()

    # Get initial count
    print("Getting track count (this may take a moment)...")
    count = get_track_count()
    if count is None:
        print("ERROR: Could not get track count. Is Music.app running?")
        print("Start Music.app and try again.")
        sys.exit(1)

    print(f"Tracks to delete: {count:,}")
    initial_count = count
    batches_done = 0
    start_time = time.time()

    while count > 0:
        batches_done += 1
        elapsed = time.time() - start_time
        deleted_so_far = initial_count - count
        rate = deleted_so_far / elapsed if elapsed > 0 and deleted_so_far > 0 else 0
        eta = count / rate if rate > 0 else 0

        print(f"\nBatch {batches_done}: deleting up to {BATCH_SIZE:,} tracks "
              f"({count:,} remaining, ~{eta/60:.0f}min left)...")

        ok, result = delete_batch(BATCH_SIZE)

        if not ok:
            if result == "TIMEOUT":
                print(f"  TIMEOUT on batch {batches_done}.")
                print(f"  Music.app may be beachballed. Stopping.")
                print(f"  Deleted {deleted_so_far:,} of {initial_count:,} so far.")
                print(f"  Force-quit Music.app, relaunch, and run this script again.")
                sys.exit(1)
            else:
                print(f"  ERROR: {result}")
                print(f"  Stopping. Deleted {deleted_so_far:,} of {initial_count:,} so far.")
                sys.exit(1)

        print(f"  Deleted batch of {result} tracks.")

        # Brief pause to let Music.app breathe
        time.sleep(1)

        # Re-check count every 10 batches (counting is slow too)
        if batches_done % 10 == 0:
            print("  Rechecking track count...")
            new_count = get_track_count()
            if new_count is not None:
                count = new_count
                print(f"  Verified: {count:,} remaining")
            else:
                count -= BATCH_SIZE  # estimate
        else:
            count -= BATCH_SIZE
            if count < 0:
                count = 0

    elapsed = time.time() - start_time
    print(f"\n All tracks deleted in {elapsed/60:.1f} minutes.")
    print("Deleting the empty playlist...")

    ok, result = delete_empty_playlist()
    if ok:
        print("Playlist deleted! You're free.")
    else:
        print(f"Could not delete empty playlist: {result}")
        print("You can delete it manually in Music.app now — it's empty.")


if __name__ == "__main__":
    main()
