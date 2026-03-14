# VERDICT: Use coordinates (mean r=0.57)
"""
Proximity PoC: compare DOM link order vs 2D coordinates on music-map.com.
Scrapes 12 diverse artists, computes Spearman rank correlation per artist,
and prints a verdict: use link-order OR coordinates for proximity scoring.

Run: python tests/poc/proximity_poc.py
"""
import math
from playwright.sync_api import sync_playwright

SKIP_HREFS = {"", "/", "/about", "/contact", "/gnod", "info", "about", "contact", "gnod"}

TEST_ARTISTS = [
    "radiohead", "tom+waits", "beyonce", "metallica", "miles+davis",
    "bjork", "kendrick+lamar", "the+beatles", "lcd+soundsystem",
    "nick+cave", "james+blake", "vampire+weekend",
]

def spearman(x, y):
    """Compute Spearman rank correlation between two lists of equal length."""
    n = len(x)
    idx_x = sorted(range(n), key=lambda i: x[i])
    idx_y = sorted(range(n), key=lambda i: y[i])
    rx, ry = [0]*n, [0]*n
    for rank, i in enumerate(idx_x):
        rx[i] = rank
    for rank, i in enumerate(idx_y):
        ry[i] = rank
    d_sq = sum((rx[i] - ry[i])**2 for i in range(n))
    return 1 - (6 * d_sq) / (n * (n**2 - 1))

def scrape_artist(page, artist_slug):
    """Return list of (name, order, dist_from_center) for each candidate link."""
    url = f"https://www.music-map.com/{artist_slug}"
    page.goto(url, timeout=20000)
    page.wait_for_load_state("networkidle", timeout=15000)

    viewport = page.viewport_size
    cx = viewport["width"] / 2
    cy = viewport["height"] / 2

    links = page.query_selector_all("a[href]")
    results = []
    order = 0
    for link in links:
        href = (link.get_attribute("href") or "").strip().lstrip("/")
        if not href or href in SKIP_HREFS or href.startswith("http"):
            continue
        name = (link.text_content() or "").strip().lower()
        if not name or name == "?":
            continue
        box = link.bounding_box()
        if box is None:
            continue
        lx = box["x"] + box["width"] / 2
        ly = box["y"] + box["height"] / 2
        dist = math.sqrt((lx - cx)**2 + (ly - cy)**2)
        results.append((name, order, dist))
        order += 1
    return results

def main():
    correlations = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        for slug in TEST_ARTISTS:
            print(f"Scraping: {slug} ...", end=" ", flush=True)
            try:
                data = scrape_artist(page, slug)
                if len(data) < 5:
                    print(f"too few links ({len(data)}), skipping")
                    continue
                orders = [d[1] for d in data]
                dists  = [d[2] for d in data]
                r = spearman(orders, dists)
                correlations.append(r)
                print(f"{len(data)} links, Spearman r = {r:.3f}")
                by_order = sorted(data, key=lambda d: d[1])[:5]
                by_dist  = sorted(data, key=lambda d: d[2])[:5]
                print(f"  Top 5 by order: {[d[0] for d in by_order]}")
                print(f"  Top 5 by dist:  {[d[0] for d in by_dist]}")
            except Exception as e:
                print(f"ERROR: {e}")
        browser.close()

    if correlations:
        avg = sum(correlations) / len(correlations)
        print(f"\n--- VERDICT ---")
        print(f"Mean Spearman r across {len(correlations)} artists: {avg:.3f}")
        if avg >= 0.95:
            print("✓ Link order correlates well with distance. USE LINK ORDER.")
        else:
            print("✗ Link order does NOT correlate well. USE COORDINATES.")

if __name__ == "__main__":
    main()
