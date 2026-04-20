"""
Reddit scraper for r/MagicArena Daily Deals posts.
Uses Reddit's .json endpoint — no API key required.
Extracts post images and HamBoneRaces' pricing tables from comments.
"""

import re
import os
import time
import json
import logging
import requests
from html import unescape
from datetime import datetime

import database

logger = logging.getLogger(__name__)

IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")

# Reddit .json endpoints
SEARCH_URL = (
    "https://www.reddit.com/r/MagicArena/search.json"
    "?q=%22Daily+Deals+-%22&type=link&sort=new&restrict_sr=on&limit=25"
)
COMMENTS_URL = "https://www.reddit.com/r/MagicArena/comments/{post_id}/.json?limit=100"

HEADERS = {
    "User-Agent": "MTGADailyDealsBot/1.0 (personal Telegram bot)"
}

# Rate limiting — be respectful
REQUEST_DELAY = 2.0

# Month name to number mapping
MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def ensure_images_dir():
    """Create the images directory if it doesn't exist."""
    os.makedirs(IMAGES_DIR, exist_ok=True)


def parse_date_from_title(title: str) -> str | None:
    """
    Extract date from a title like 'Daily Deals - April 20, 2026: ...'
    Returns YYYYMMDD string or None if parsing fails.
    """
    # Pattern: "Daily Deals - MonthName DD, YYYY"
    match = re.search(
        r'Daily\s+Deals\s*-\s*(\w+)\s+(\d{1,2}),?\s*(\d{4})',
        title, re.IGNORECASE
    )
    if not match:
        return None

    month_name = match.group(1).lower()
    day = int(match.group(2))
    year = int(match.group(3))

    month = MONTH_MAP.get(month_name)
    if not month:
        return None

    return f"{year:04d}{month:02d}{day:02d}"


def parse_markdown_table(body: str) -> list[dict] | None:
    """
    Parse a Reddit markdown table from a comment body.
    Returns a list of dicts with column headers as keys, or None if no table found.

    Example input:
        Card Sytle|Gems|Gold
        :---|:---:|:---:
        Draft Token|1,350|9,000
        [[Riling Dawnbreaker]]|50|250
    """
    lines = body.split("\n")
    table_lines = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_table:
                break  # End of table block
            continue

        # Detect table rows — must have pipes and not be just a separator
        if "|" in stripped:
            # Skip separator rows like :---|:---:|:---:
            if re.match(r'^[\s|:\-]+$', stripped):
                in_table = True
                continue
            table_lines.append(stripped)
            in_table = True
        elif in_table:
            break  # Non-table line after table started → table ended

    if len(table_lines) < 2:
        return None

    # First line is headers
    headers = [h.strip() for h in table_lines[0].split("|") if h.strip()]

    rows = []
    for row_line in table_lines[1:]:
        cells = [c.strip() for c in row_line.split("|")]
        # Remove empty leading/trailing cells from pipe-delimited format
        cells = [c for c in cells if c or len(cells) <= len(headers)]

        # Clean up [[Card Name]] markup
        cleaned_cells = []
        for cell in cells:
            cell = re.sub(r'\[\[([^\]]+)\]\]', r'\1', cell)
            cleaned_cells.append(cell)

        if len(cleaned_cells) >= len(headers):
            row_dict = {}
            for i, header in enumerate(headers):
                row_dict[header] = cleaned_cells[i] if i < len(cleaned_cells) else ""
            rows.append(row_dict)

    return rows if rows else None


def download_image(image_url: str, date_key: str) -> str | None:
    """
    Download an image from a URL and save it locally.
    Returns the local file path or None on failure.
    """
    ensure_images_dir()

    # Determine file extension
    # Clean up URL (remove query params for extension detection)
    clean_url = image_url.split("?")[0]
    ext = os.path.splitext(clean_url)[1] or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        ext = ".jpg"

    filename = f"{date_key}{ext}"
    filepath = os.path.join(IMAGES_DIR, filename)

    # Skip if already downloaded
    if os.path.exists(filepath):
        logger.info(f"Image already exists: {filepath}")
        return filepath

    try:
        logger.info(f"Downloading image: {image_url}")
        response = requests.get(image_url, headers=HEADERS, timeout=30)
        response.raise_for_status()

        with open(filepath, "wb") as f:
            f.write(response.content)

        logger.info(f"Saved image to: {filepath}")
        return filepath
    except Exception as e:
        logger.error(f"Failed to download image: {e}")
        return None


def fetch_json(url: str) -> dict | None:
    """Fetch a JSON endpoint from Reddit with rate limiting."""
    time.sleep(REQUEST_DELAY)
    try:
        logger.info(f"Fetching: {url}")
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None


def find_hambone_comment(comments_data: list) -> str | None:
    """
    Find HamBoneRaces' comment with the pricing table in a post's comments.
    Returns the comment body text or None.
    """
    if not comments_data or len(comments_data) < 2:
        return None

    comment_listing = comments_data[1]
    if comment_listing.get("kind") != "Listing":
        return None

    children = comment_listing.get("data", {}).get("children", [])
    for child in children:
        if child.get("kind") != "t1":
            continue
        comment_data = child.get("data", {})
        author = comment_data.get("author", "")
        body = comment_data.get("body", "")

        # Look for HamBoneRaces' comment that contains a table
        if author == "HamBoneRaces" and "|" in body:
            return body

    return None


def scrape_daily_deals() -> int:
    """
    Main scraping function. Fetches latest Daily Deals posts from Reddit,
    extracts image + table data, and saves to the database.
    Returns the number of new deals saved.
    """
    logger.info("Starting Daily Deals scrape...")

    # Step 1: Search for recent Daily Deals posts
    search_data = fetch_json(SEARCH_URL)
    if not search_data:
        logger.error("Failed to fetch search results")
        return 0

    children = search_data.get("data", {}).get("children", [])
    logger.info(f"Found {len(children)} search results")

    new_deals = 0

    for child in children:
        post = child.get("data", {})
        post_id = post.get("id", "")
        title = unescape(post.get("title", ""))
        author = post.get("author", "")
        subreddit = post.get("subreddit", "")
        permalink = post.get("permalink", "")
        image_url = post.get("url", "")

        # Filter: only r/MagicArena posts by HamBoneRaces
        if subreddit != "MagicArena" or author != "HamBoneRaces":
            continue

        # Check title is a Daily Deals post
        if "Daily Deals" not in title:
            continue

        # Skip if already in database
        if database.post_exists(post_id):
            logger.debug(f"Already scraped: {title}")
            continue

        logger.info(f"Processing: {title}")

        # Parse the date from the title
        date_key = parse_date_from_title(title)
        if not date_key:
            logger.warning(f"Could not parse date from title: {title}")
            continue

        # Download the image
        image_path = None
        if image_url and ("i.redd.it" in image_url or "preview.redd.it" in image_url):
            image_path = download_image(image_url, date_key)

        # Fetch comments to find HamBoneRaces' table
        table_data = None
        comments_url = COMMENTS_URL.format(post_id=post_id)
        comments_json = fetch_json(comments_url)
        if comments_json:
            hambone_body = find_hambone_comment(comments_json)
            if hambone_body:
                table_data = parse_markdown_table(hambone_body)
                if table_data:
                    logger.info(f"Extracted table with {len(table_data)} rows")
                else:
                    logger.warning(f"Found HamBoneRaces comment but couldn't parse table")
            else:
                logger.warning(f"No HamBoneRaces table comment found for: {title}")

        # Build the full Reddit URL
        reddit_url = f"https://www.reddit.com{permalink}" if permalink else ""

        # Save to database
        saved = database.save_deal(
            date_key=date_key,
            title=title,
            image_path=image_path,
            table_data=table_data,
            reddit_post_id=post_id,
            reddit_url=reddit_url,
        )
        if saved:
            new_deals += 1
            logger.info(f"Saved deal for {date_key}: {title}")
        else:
            logger.debug(f"Deal already existed for date {date_key}")

    logger.info(f"Scrape complete. {new_deals} new deals saved.")
    return new_deals


# Allow running the scraper standalone for testing
if __name__ == "__main__":
    import sys
    # Fix Windows console encoding for emoji/unicode
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    count = scrape_daily_deals()
    print(f"\nDone! {count} new deals scraped.")

    # Show latest deal
    latest = database.get_latest_deal()
    if latest:
        print(f"\nLatest deal: {latest['title']}")
        print(f"  Date key: {latest['date_key']}")
        print(f"  Image: {latest['image_path']}")
        if latest['table_data']:
            print(f"  Table rows: {len(latest['table_data'])}")
            for row in latest['table_data']:
                print(f"    {row}")
