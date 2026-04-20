"""
Scraper for MTG Arena Ranked Events from the official Wizards page.
Parses the HTML table and stores event data with date-based status tracking.
"""

import re
import logging
import json
import requests
from html import unescape
from datetime import datetime, date

import database

logger = logging.getLogger(__name__)

RANKED_SEASON_URL = "https://magic.wizards.com/en/news/mtg-arena/ranked-season"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MTGADailyDealsBot/1.0)"
}


def parse_date_string(date_str: str) -> date | None:
    """
    Parse a date string like '3/3/2026' or '4/20/2026' into a date object.
    Returns None for permanent events (∞).
    """
    date_str = date_str.strip()
    if not date_str or date_str in ("∞", "&infin;", "∞"):
        return None

    # Try M/D/YYYY format
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue

    return None


def get_event_status(start_str: str, end_str: str, today: date = None) -> str:
    """
    Determine the status of an event based on its dates.
    Returns: 'permanent', 'ended', 'active', or 'upcoming'
    """
    if today is None:
        today = date.today()

    start_date = parse_date_string(start_str)
    end_date = parse_date_string(end_str)

    # Permanent events (∞/∞)
    if start_date is None and end_date is None:
        return "permanent"

    # Has an end date in the past → ended
    if end_date and end_date < today:
        return "ended"

    # Has started and hasn't ended → active
    if start_date and start_date <= today:
        if end_date is None or end_date >= today:
            return "active"

    # Hasn't started yet → upcoming
    if start_date and start_date > today:
        return "upcoming"

    return "active"  # Default fallback


def parse_events_table(html: str) -> list[dict] | None:
    """
    Parse the Ranked Events table from the Wizards page HTML.
    Returns a list of dicts with keys: event, format, start, end
    """
    # Find the table that contains "Ranked Events" header
    # The table is a standard HTML table with <th>Ranked Events</th>
    table_match = re.search(
        r'<table[^>]*>.*?<th>Ranked Events</th>.*?</table>',
        html, re.DOTALL | re.IGNORECASE
    )

    if not table_match:
        logger.error("Could not find Ranked Events table in HTML")
        return None

    table_html = table_match.group(0)

    # Extract all rows (skip the header row)
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL | re.IGNORECASE)

    events = []
    for row in rows:
        # Skip header rows
        if '<th>' in row.lower() or '<th ' in row.lower():
            continue

        # Extract cell contents
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL | re.IGNORECASE)

        if len(cells) < 4:
            continue

        # Clean up cell text (strip HTML tags, whitespace, decode entities)
        cleaned = []
        for cell in cells[:4]:
            text = re.sub(r'<[^>]+>', '', cell)  # Strip HTML tags
            text = unescape(text)  # Decode &infin; etc.
            text = text.strip()
            text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
            cleaned.append(text)

        event = {
            "event": cleaned[0],
            "format": cleaned[1],
            "start": cleaned[2],
            "end": cleaned[3],
        }
        events.append(event)

    return events if events else None


def scrape_events() -> int:
    """
    Scrape the Ranked Events table and save to database.
    Returns the number of events saved (0 if unchanged or failed).
    """
    logger.info("Scraping MTGA Ranked Events...")

    try:
        response = requests.get(RANKED_SEASON_URL, headers=HEADERS, timeout=30)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch ranked season page: {e}")
        return 0

    events = parse_events_table(response.text)
    if not events:
        logger.error("Failed to parse events table")
        return 0

    logger.info(f"Parsed {len(events)} events from the page")

    # Check if the data has changed since last scrape
    today_key = date.today().strftime("%Y%m%d")
    existing = database.get_latest_events()

    if existing and existing["date_key"] == today_key:
        # Compare the actual data
        if existing["events_data"] == events:
            logger.info("Events data unchanged since last scrape today, skipping")
            return 0

    # Save to database
    saved = database.save_events(
        date_key=today_key,
        events_data=events,
    )

    if saved:
        logger.info(f"Saved {len(events)} events for {today_key}")
        return len(events)
    else:
        logger.debug(f"Events already existed for {today_key}")
        return 0


# Allow running standalone for testing
if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    count = scrape_events()
    print(f"\nDone! {count} events scraped.")

    latest = database.get_latest_events()
    if latest:
        print(f"\nLatest events (scraped {latest['date_key']}):")
        today = date.today()
        for ev in latest["events_data"]:
            status = get_event_status(ev["start"], ev["end"], today)
            print(f"  [{status:>9}] {ev['event'][:50]:<50} | {ev['format']:<30} | {ev['start']:>12} | {ev['end']:>12}")
