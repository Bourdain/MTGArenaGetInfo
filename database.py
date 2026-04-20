"""
SQLite database operations for MTGA Daily Deals.
Stores scraped daily deal data with date-keyed lookups.
"""

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daily_deals.db")


def get_connection():
    """Get a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the database schema."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_key TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            image_path TEXT,
            table_data TEXT,
            reddit_post_id TEXT UNIQUE NOT NULL,
            reddit_url TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def post_exists(reddit_post_id: str) -> bool:
    """Check if a post has already been scraped."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM daily_deals WHERE reddit_post_id = ?", (reddit_post_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def date_exists(date_key: str) -> bool:
    """Check if a date_key already has data."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM daily_deals WHERE date_key = ?", (date_key,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def save_deal(date_key: str, title: str, image_path: str,
              table_data: list, reddit_post_id: str, reddit_url: str):
    """Save a daily deal to the database."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR IGNORE INTO daily_deals
            (date_key, title, image_path, table_data, reddit_post_id, reddit_url)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            date_key,
            title,
            image_path,
            json.dumps(table_data) if table_data else None,
            reddit_post_id,
            reddit_url,
        ))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_latest_deal() -> dict | None:
    """Get the most recent daily deal by date_key."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM daily_deals
        ORDER BY date_key DESC
        LIMIT 1
    """)
    row = cursor.fetchone()
    conn.close()
    if row:
        return _row_to_dict(row)
    return None


def get_deal_by_date(date_key: str) -> dict | None:
    """Get a daily deal by its YYYYMMDD date key."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM daily_deals WHERE date_key = ?", (date_key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return _row_to_dict(row)
    return None


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a database row to a dictionary, parsing JSON fields."""
    d = dict(row)
    if d.get("table_data"):
        try:
            d["table_data"] = json.loads(d["table_data"])
        except (json.JSONDecodeError, TypeError):
            d["table_data"] = None
    return d


# Initialize the database on import
init_db()
