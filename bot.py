"""
MTGA Daily Deals Telegram Bot.
Listens for !MTGAStore commands and posts daily deal images + pricing tables.
Runs a background scraper on a configurable interval.
"""

import os
import logging
from datetime import datetime

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

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SCRAPE_INTERVAL_HOURS = int(os.getenv("SCRAPE_INTERVAL_HOURS", "6"))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
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
    Handle the !MTGAStore command.
    - !MTGAStore → latest deal
    - !MTGAStore YYYYMMDD → specific date
    """
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    # Parse command and optional date argument
    parts = text.split()
    date_arg = None
    if len(parts) >= 2:
        date_arg = parts[1].strip()

    # Fetch the deal
    if date_arg:
        # Validate YYYYMMDD format
        if len(date_arg) != 8 or not date_arg.isdigit():
            await update.message.reply_text(
                "❌ Invalid date format. Use YYYYMMDD (e.g., !MTGAStore 20260420)"
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


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start and /help commands."""
    help_text = (
        "🃏 <b>MTGA Daily Deals Bot</b>\n\n"
        "I track Magic: The Gathering Arena daily deals from Reddit!\n\n"
        "<b>Commands:</b>\n"
        "• <code>!MTGAStore</code> — Show today's daily deal\n"
        "• <code>!MTGAStore YYYYMMDD</code> — Show a specific day's deal\n"
        "• <code>/help</code> — Show this message\n\n"
        "Data is scraped from r/MagicArena posts by HamBoneRaces.\n"
        f"Auto-scraping runs every {SCRAPE_INTERVAL_HOURS} hours."
    )
    await update.message.reply_text(help_text, parse_mode="HTML")


async def scheduled_scrape(context: ContextTypes.DEFAULT_TYPE):
    """Background job that runs the scraper periodically."""
    logger.info("Running scheduled scrape...")
    try:
        count = scraper.scrape_daily_deals()
        logger.info(f"Scheduled scrape complete. {count} new deals found.")
    except Exception as e:
        logger.error(f"Scheduled scrape failed: {e}", exc_info=True)


def main():
    """Start the Telegram bot with background scraping."""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("❌ ERROR: Please set your TELEGRAM_BOT_TOKEN in the .env file!")
        print("   Get a token from @BotFather on Telegram.")
        return

    logger.info("Starting MTGA Daily Deals Bot...")

    # Run an initial scrape before starting
    logger.info("Running initial scrape...")
    try:
        count = scraper.scrape_daily_deals()
        logger.info(f"Initial scrape complete. {count} new deals found.")
    except Exception as e:
        logger.error(f"Initial scrape failed: {e}", exc_info=True)

    # Build the Telegram bot application
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Register handlers

    # !MTGAStore command (detected via message text, not /command)
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r"(?i)^!MTGAStore"),
        handle_mtgastore,
    ))

    # Standard /help and /start commands
    app.add_handler(CommandHandler("start", handle_help))
    app.add_handler(CommandHandler("help", handle_help))

    # Schedule background scraping
    job_queue = app.job_queue
    if job_queue:
        # Run every SCRAPE_INTERVAL_HOURS hours
        job_queue.run_repeating(
            scheduled_scrape,
            interval=SCRAPE_INTERVAL_HOURS * 3600,
            first=SCRAPE_INTERVAL_HOURS * 3600,  # First run after interval
            name="scrape_daily_deals",
        )
        logger.info(f"Scheduled scraping every {SCRAPE_INTERVAL_HOURS} hours")
    else:
        logger.warning("Job queue not available — scheduled scraping disabled")

    # Start polling
    logger.info("Bot is running! Listening for messages...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
