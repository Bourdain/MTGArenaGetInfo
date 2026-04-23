"""
SQLite database operations for MTGA Daily Deals and Ranked Events.
Stores scraped daily deal data and events with date-keyed lookups.
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            chat_id INTEGER PRIMARY KEY,
            subscribed_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ranked_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_key TEXT UNIQUE NOT NULL,
            events_data TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            deal_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            retry_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_attempted_at TEXT,
            error_message TEXT,
            FOREIGN KEY (chat_id) REFERENCES subscriptions(chat_id),
            FOREIGN KEY (deal_id) REFERENCES daily_deals(id),
            UNIQUE(chat_id, deal_id)
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


def get_deal_by_id(deal_id: int) -> dict | None:
    """Get a daily deal by its primary key ID."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM daily_deals WHERE id = ?", (deal_id,))
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


def subscribe_chat(chat_id: int) -> bool:
    """Subscribe a chat to automatic deal notifications. Returns True if newly subscribed."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO subscriptions (chat_id) VALUES (?)", (chat_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def unsubscribe_chat(chat_id: int) -> bool:
    """Unsubscribe a chat from notifications. Returns True if was subscribed."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM subscriptions WHERE chat_id = ?", (chat_id,))
    conn.commit()
    removed = cursor.rowcount > 0
    conn.close()
    return removed


def is_subscribed(chat_id: int) -> bool:
    """Check if a chat is subscribed."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM subscriptions WHERE chat_id = ?", (chat_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def get_subscribed_chats() -> list[int]:
    """Get all subscribed chat IDs."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id FROM subscriptions")
    chat_ids = [row["chat_id"] for row in cursor.fetchall()]
    conn.close()
    return chat_ids


# --- Pending Messages Queue ---

def enqueue_deal_notifications(deal_id: int) -> int:
    """
    Create a pending message for every subscribed chat for the given deal.
    Uses INSERT OR IGNORE to avoid duplicates (UNIQUE chat_id + deal_id).
    Returns the number of messages enqueued.
    """
    conn = get_connection()
    cursor = conn.cursor()
    chat_ids = get_subscribed_chats()
    enqueued = 0
    for chat_id in chat_ids:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO pending_messages (chat_id, deal_id)
                VALUES (?, ?)
            """, (chat_id, deal_id))
            enqueued += cursor.rowcount
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    conn.close()
    return enqueued


def get_pending_messages(limit: int = 50) -> list[dict]:
    """
    Fetch pending messages that are eligible for dispatch.
    Returns messages with status 'pending' and retry_count < 3,
    joined with deal data, ordered by creation time.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            pm.id AS message_id,
            pm.chat_id,
            pm.deal_id,
            pm.retry_count,
            pm.status
        FROM pending_messages pm
        WHERE pm.status = 'pending' AND pm.retry_count < 3
        ORDER BY pm.created_at ASC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def mark_message_sent(message_id: int):
    """Mark a pending message as successfully sent."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE pending_messages
        SET status = 'sent', last_attempted_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (message_id,))
    conn.commit()
    conn.close()


def mark_message_failed(message_id: int, error: str):
    """
    Record a failed send attempt. Increments retry_count and stores the error.
    If retry_count reaches 3, status is set to 'failed' permanently.
    Otherwise status stays 'pending' for the next dispatch cycle.
    """
    conn = get_connection()
    cursor = conn.cursor()
    # Increment retry count and decide new status
    cursor.execute("SELECT retry_count FROM pending_messages WHERE id = ?", (message_id,))
    row = cursor.fetchone()
    if row:
        new_count = row["retry_count"] + 1
        new_status = 'failed' if new_count >= 3 else 'pending'
        cursor.execute("""
            UPDATE pending_messages
            SET retry_count = ?, status = ?, last_attempted_at = CURRENT_TIMESTAMP,
                error_message = ?
            WHERE id = ?
        """, (new_count, new_status, error, message_id))
    conn.commit()
    conn.close()


# --- Ranked Events ---

def save_events(date_key: str, events_data: list) -> bool:
    """Save ranked events data for a given date."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO ranked_events (date_key, events_data)
            VALUES (?, ?)
        """, (date_key, json.dumps(events_data)))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_latest_events() -> dict | None:
    """Get the most recently scraped events data."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM ranked_events
        ORDER BY date_key DESC
        LIMIT 1
    """)
    row = cursor.fetchone()
    conn.close()
    if row:
        d = dict(row)
        try:
            d["events_data"] = json.loads(d["events_data"])
        except (json.JSONDecodeError, TypeError):
            d["events_data"] = None
        return d
    return None


# Initialize the database on import
init_db()
