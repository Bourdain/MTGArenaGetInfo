# MTGA Daily Deals Telegram Bot

A Python Telegram bot that scrapes [r/MagicArena](https://www.reddit.com/r/MagicArena/) Daily Deals posts (by HamBoneRaces), stores them in a local SQLite database, and serves them on demand via Telegram commands.

## Features

- **Automatic scraping** — Fetches new Daily Deal posts every X hours (configurable)
- **Image + pricing table** — Sends the deal screenshot and a formatted pricing table
- **Date lookup** — Query deals for any specific date
- **Local storage** — SQLite database with downloaded images for offline access

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure your Telegram token

Edit the `.env` file and paste your bot token from [@BotFather](https://t.me/BotFather):

```env
TELEGRAM_BOT_TOKEN=your_actual_token_here
SCRAPE_INTERVAL_HOURS=6
```

### 3. Run the bot

```bash
python bot.py
```

The bot will:
1. Run an initial scrape on startup
2. Start listening for Telegram messages
3. Automatically re-scrape every 6 hours (or as configured)

## Commands

| Command | Description |
|---|---|
| `!MTGAStore` | Shows the most recent daily deal |
| `!MTGAStore YYYYMMDD` | Shows the deal for a specific date (e.g., `!MTGAStore 20260420`) |
| `/help` | Shows help message |

## Testing the scraper standalone

```bash
python scraper.py
```

This will run a scrape and print the results without starting the Telegram bot.

## Project Structure

```
MTGArenaGetInfo/
├── .env                 # Bot token & config (not tracked by git)
├── .gitignore           # Ignores .env, db, images, etc.
├── requirements.txt     # Python dependencies
├── bot.py               # Telegram bot entry point
├── scraper.py           # Reddit scraping logic
├── database.py          # SQLite operations
├── daily_deals.db       # SQLite database (auto-created)
└── images/              # Downloaded deal images (auto-created)
```

## How it works

1. **Scraper** hits Reddit's `.json` endpoint to search for "Daily Deals -" posts in r/MagicArena
2. Filters results to posts by **HamBoneRaces** only
3. For each new post:
   - Parses the date from the title (e.g., "Daily Deals - April 20, 2026")
   - Downloads the attached image
   - Fetches comments to find HamBoneRaces' pricing table (markdown table with Card Style, Gems, Gold)
4. Saves everything to SQLite keyed by `YYYYMMDD`
5. Bot responds to `!MTGAStore` by looking up the latest (or specified) deal and sending the image + formatted table
