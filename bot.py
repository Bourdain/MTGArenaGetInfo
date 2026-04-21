"""
MTGA Daily Deals Telegram Bot.
Listens for !MTGAStore commands and posts daily deal images + pricing tables.
Runs a background scraper on a configurable interval.
"""

import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, date

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)

import database
import scraper
import events_scraper

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SCRAPE_INTERVAL_MINUTES = int(os.getenv("SCRAPE_INTERVAL_MINUTES", "30"))

# Configure logging — write to both console and a rotating log file
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.log")

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
root_logger.addHandler(console_handler)

# File handler (5 MB per file, keep 3 backups)
file_handler = RotatingFileHandler(
    LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)


def format_table_text(deal: dict) -> str:
    """
    Format a daily deal into a Telegram-friendly message.
    Uses monospace formatting for the table so columns align.
    """
    title = deal.get("title", "Unknown Deal")
    date_key = deal.get("date_key", "")
    table_data = deal.get("table_data")
    reddit_url = deal.get("reddit_url", "")

    # Header
    lines = [f"📅 <b>{title}</b>"]

    if date_key:
        # Format YYYYMMDD as a readable date
        try:
            dt = datetime.strptime(date_key, "%Y%m%d")
            lines.append(f"📆 {dt.strftime('%B %d, %Y')}")
        except ValueError:
            lines.append(f"📆 {date_key}")

    lines.append("")

    # Table
    if table_data and isinstance(table_data, list) and len(table_data) > 0:
        # Determine column headers from the first row's keys
        headers = list(table_data[0].keys())

        # Calculate column widths
        col_widths = {}
        for h in headers:
            col_widths[h] = len(h)
        for row in table_data:
            for h in headers:
                val = str(row.get(h, ""))
                col_widths[h] = max(col_widths[h], len(val))

        # Build the formatted table
        # Header row
        header_line = " | ".join(h.ljust(col_widths[h]) for h in headers)
        separator = "-+-".join("-" * col_widths[h] for h in headers)

        lines.append(f"<pre>{header_line}")
        lines.append(separator)

        for row in table_data:
            row_line = " | ".join(
                str(row.get(h, "")).ljust(col_widths[h]) for h in headers
            )
            lines.append(row_line)

        lines.append("</pre>")
    else:
        lines.append("<i>No pricing table available for this day.</i>")

    # Reddit link
    if reddit_url:
        lines.append("")
        lines.append(f'🔗 <a href="{reddit_url}">View on Reddit</a>')

    return "\n".join(lines)


async def handle_mtgastore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /MTGAStore command.
    - /MTGAStore → latest deal
    - /MTGAStore YYYYMMDD → specific date
    """
    if not update.message:
        return

    # context.args contains everything after the command
    date_arg = context.args[0].strip() if context.args else None

    # Fetch the deal
    if date_arg:
        # Validate YYYYMMDD format
        if len(date_arg) != 8 or not date_arg.isdigit():
            await update.message.reply_text(
                "❌ Invalid date format. Use YYYYMMDD (e.g., /MTGAStore 20260420)"
            )
            return
        deal = database.get_deal_by_date(date_arg)
        if not deal:
            await update.message.reply_text(
                f"❌ No daily deal found for {date_arg}.\n"
                "The data might not have been scraped yet."
            )
            return
    else:
        deal = database.get_latest_deal()
        if not deal:
            await update.message.reply_text(
                "❌ No daily deals in the database yet.\n"
                "The scraper may not have run yet — try again later."
            )
            return

    # Format the message
    message_text = format_table_text(deal)

    # Try to send the image
    image_sent = False
    image_path = deal.get("image_path")
    if image_path and os.path.exists(image_path):
        try:
            with open(image_path, "rb") as photo:
                await update.message.reply_photo(
                    photo=photo,
                    caption=message_text,
                    parse_mode="HTML",
                )
                image_sent = True
        except Exception as e:
            logger.error(f"Failed to send image: {e}")

    # If image failed or doesn't exist, send text only
    if not image_sent:
        await update.message.reply_text(
            message_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


async def send_deal_to_chat(bot, chat_id: int, deal: dict):
    """
    Send a deal (image + table) to a specific chat.
    Used by both the !MTGAStore command and auto-notifications.
    """
    message_text = format_table_text(deal)
    image_sent = False
    image_path = deal.get("image_path")

    if image_path and os.path.exists(image_path):
        try:
            with open(image_path, "rb") as photo:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=message_text,
                    parse_mode="HTML",
                )
                image_sent = True
        except Exception as e:
            logger.error(f"Failed to send image to {chat_id}: {e}")

    if not image_sent:
        await bot.send_message(
            chat_id=chat_id,
            text=message_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


async def handle_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /MTGAStoreSubscribe — subscribe this chat to auto-notifications."""
    if not update.message:
        return

    chat_id = update.message.chat_id
    is_new = database.subscribe_chat(chat_id)

    if is_new:
        await update.message.reply_text(
            "✅ Subscribed! This chat will automatically receive new daily deals "
            "as they are scraped."
        )
    else:
        await update.message.reply_text(
            "ℹ️ This chat is already subscribed."
        )


async def handle_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /MTGAStoreUnsubscribe — unsubscribe this chat from auto-notifications."""
    if not update.message:
        return

    chat_id = update.message.chat_id
    was_subscribed = database.unsubscribe_chat(chat_id)

    if was_subscribed:
        await update.message.reply_text(
            "🔕 Unsubscribed. This chat will no longer receive automatic deal updates."
        )
    else:
        await update.message.reply_text(
            "ℹ️ This chat was not subscribed."
        )


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start and /help commands."""
    help_text = (
        "🃏 <b>MTGA Daily Deals Bot</b>\n\n"
        "I track Magic: The Gathering Arena daily deals from Reddit!\n\n"
        "<b>Commands:</b>\n"
        "• <code>/MTGAStore</code> — Show today's daily deal\n"
        "• <code>/MTGAStore YYYYMMDD</code> — Show a specific day's deal\n"
        "• <code>/MTGAEvents</code> — Show current ranked events schedule\n"
        "• <code>/MTGAStoreSubscribe</code> — Auto-receive new deals in this chat\n"
        "• <code>/MTGAStoreUnsubscribe</code> — Stop auto-receiving deals\n"
        "• <code>/help</code> — Show this message\n\n"
        "Data is scraped from r/MagicArena posts by HamBoneRaces.\n"
        f"Auto-scraping runs every {SCRAPE_INTERVAL_MINUTES} minutes."
    )
    await update.message.reply_text(help_text, parse_mode="HTML")


def _fmt_date(d: str) -> str:
    """Convert M/D/YYYY to YYYY-MM-DD. Passes through ∞ unchanged."""
    d = d.strip()
    if not d or d == "∞":
        return d
    try:
        parsed = datetime.strptime(d, "%m/%d/%Y")
        return parsed.strftime("%Y-%m-%d")
    except ValueError:
        return d


async def handle_mtgaevents(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /mtgaevents command — show current ranked events with status colors."""
    if not update.message:
        return

    latest = database.get_latest_events()
    if not latest or not latest.get("events_data"):
        await update.message.reply_text(
            "❌ No events data available yet. The scraper may not have run."
        )
        return

    events = latest["events_data"]
    today = date.today()
    scrape_date = latest.get("date_key", "")

    # Categorize limited-time events only (skip permanent ∞/∞ events)
    groups = {
        "🎭 Player Draft": [],
        "🤖 Bot Draft": [],
    }

    for ev in events:
        status = events_scraper.get_event_status(ev["start"], ev["end"], today)
        ev["_status"] = status

        # Skip permanent events
        if status == "permanent":
            continue

        fmt = ev["format"]
        if "Bot Draft" in fmt:
            groups["🤖 Bot Draft"].append(ev)
        else:
            groups["🎭 Player Draft"].append(ev)

    # Build message
    formatted_date = f"{scrape_date[:4]}-{scrape_date[4:6]}-{scrape_date[6:]}" if len(scrape_date) == 8 else scrape_date
    lines = [
        "🏆 <b>MTGA Ranked Events</b>",
        f"📆 Updated: {formatted_date}",
        "",
        "🟢 Active  •  ⚪ Upcoming  •  🔴 Ended",
    ]

    for group_name, group_events in groups.items():
        if not group_events:
            continue

        lines.append("")
        lines.append(f"━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"<b>{group_name}</b>")
        lines.append(f"━━━━━━━━━━━━━━━━━━━━")

        for ev in group_events:
            status = ev["_status"]
            name = ev["event"]
            start = _fmt_date(ev["start"])
            end = _fmt_date(ev["end"])

            if status == "ended":
                lines.append(f"  🔴 <s>{name}</s>")
                lines.append(f"      📅 {start} → {end}")
            elif status == "active":
                lines.append(f"  🟢 <b>{name}</b>")
                lines.append(f"      📅 {start} → {end}")
            else:  # upcoming
                lines.append(f"  ⚪ {name}")
                lines.append(f"      📅 {start} → {end}")

    lines.append("")
    lines.append("🔗 <a href=\"https://magic.wizards.com/en/news/mtg-arena/ranked-season\">Full details on Wizards</a>")

    message = "\n".join(lines)

    # Telegram limit is 4096 chars — split if needed
    if len(message) <= 4096:
        await update.message.reply_text(message, parse_mode="HTML", disable_web_page_preview=True)
    else:
        # Split into chunks at section boundaries
        chunks = []
        current = ""
        for line in lines:
            if len(current) + len(line) + 1 > 4000:
                chunks.append(current)
                current = line
            else:
                current = current + "\n" + line if current else line
        if current:
            chunks.append(current)

        for chunk in chunks:
            await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)


async def scheduled_scrape(context: ContextTypes.DEFAULT_TYPE):
    """Background job that runs the scraper periodically. Notifies subscribers on new deals."""
    logger.info("Running scheduled scrape...")
    try:
        # Remember what the latest deal was before scraping
        old_latest = database.get_latest_deal()
        old_date_key = old_latest["date_key"] if old_latest else None

        count = scraper.scrape_daily_deals()
        logger.info(f"Scheduled scrape complete. {count} new deals found.")

        # If new deals were found, notify subscribers with the latest one
        if count > 0:
            new_latest = database.get_latest_deal()
            if new_latest and new_latest["date_key"] != old_date_key:
                subscribed_chats = database.get_subscribed_chats()
                if subscribed_chats:
                    logger.info(f"Notifying {len(subscribed_chats)} subscribed chats...")
                    for chat_id in subscribed_chats:
                        try:
                            await send_deal_to_chat(context.bot, chat_id, new_latest)
                        except Exception as e:
                            logger.error(f"Failed to notify chat {chat_id}: {e}")
    except Exception as e:
        logger.error(f"Scheduled scrape failed: {e}", exc_info=True)


async def scheduled_events_scrape(context: ContextTypes.DEFAULT_TYPE):
    """Background job that scrapes the ranked events page daily."""
    logger.info("Running scheduled events scrape...")
    try:
        count = events_scraper.scrape_events()
        logger.info(f"Scheduled events scrape complete. {count} events found.")
    except Exception as e:
        logger.error(f"Scheduled events scrape failed: {e}", exc_info=True)


def main():
    """Start the Telegram bot with background scraping."""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("❌ ERROR: Please set your TELEGRAM_BOT_TOKEN in the .env file!")
        print("   Get a token from @BotFather on Telegram.")
        return

    logger.info("Starting MTGA Daily Deals Bot...")

    # Run initial scrapes before starting
    logger.info("Running initial scrapes...")
    try:
        count = scraper.scrape_daily_deals()
        logger.info(f"Initial deal scrape complete. {count} new deals found.")
    except Exception as e:
        logger.error(f"Initial deal scrape failed: {e}", exc_info=True)

    try:
        ev_count = events_scraper.scrape_events()
        logger.info(f"Initial events scrape complete. {ev_count} events found.")
    except Exception as e:
        logger.error(f"Initial events scrape failed: {e}", exc_info=True)

    # Build the Telegram bot application
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Register handlers

    # Subscribe/Unsubscribe (registered before MTGAStore so they match first)
    app.add_handler(CommandHandler("mtgastoresubscribe", handle_subscribe))
    app.add_handler(CommandHandler("mtgastoreunsubscribe", handle_unsubscribe))

    # /MTGAStore command
    app.add_handler(CommandHandler("mtgastore", handle_mtgastore))

    # /MTGAEvents command
    app.add_handler(CommandHandler("mtgaevents", handle_mtgaevents))

    # Standard /help and /start commands
    app.add_handler(CommandHandler("start", handle_help))
    app.add_handler(CommandHandler("help", handle_help))

    # Schedule background scraping
    job_queue = app.job_queue
    if job_queue:
        # Run every SCRAPE_INTERVAL_MINUTES minutes
        job_queue.run_repeating(
            scheduled_scrape,
            interval=SCRAPE_INTERVAL_MINUTES * 60,
            first=SCRAPE_INTERVAL_MINUTES * 60,  # First run after interval
            name="scrape_daily_deals",
        )
        logger.info(f"Scheduled deal scraping every {SCRAPE_INTERVAL_MINUTES} minutes")

        # Scrape events once per day (every 24 hours)
        job_queue.run_repeating(
            scheduled_events_scrape,
            interval=86400,       # every 24 hours
            first=86400,          # first run after 24 hours
            name="scrape_events",
        )
        logger.info("Scheduled events scraping every 24 hours")
    else:
        logger.warning("Job queue not available — scheduled scraping disabled")

    # Start polling
    logger.info("Bot is running! Listening for messages...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
