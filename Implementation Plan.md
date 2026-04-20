\# MTGA Daily Deals Telegram Bot



A Python Telegram bot that scrapes r/MagicArena "Daily Deals" posts, stores data in SQLite, and responds to commands.



\## Proposed Changes



\### Project Structure (`c:\\Users\\Boubouchan\\source\\repos\\MTGArenaGetInfo\\`)



\#### \[NEW] `.env` — Telegram token placeholder

\#### \[NEW] `requirements.txt` — Python dependencies

\#### \[NEW] `bot.py` — Main bot entry point (Telegram bot + scheduler)

\#### \[NEW] `scraper.py` — Reddit scraping logic via `.json` endpoints

\#### \[NEW] `database.py` — SQLite database models and operations

\#### \[NEW] `README.md` — Setup \& usage instructions



\---



\## Architecture



\### Data Scraping (`scraper.py`)

\- Uses Reddit's `.json` endpoint trick (no API key needed):

&#x20; - Search: `https://www.reddit.com/r/MagicArena/search.json?q="Daily+Deals+-"\&type=link\&sort=new\&restrict\_sr=on\&limit=10`

&#x20; - Comments: `https://www.reddit.com/r/MagicArena/comments/{post\_id}/.json`

\- Filters to `r/MagicArena` posts by \*\*HamBoneRaces\*\* only

\- From each post extracts:

&#x20; - \*\*Image URL\*\* from the `url` field (direct i.redd.it link)

&#x20; - \*\*Date\*\* parsed from the title (e.g., "Daily Deals - April 20, 2026: ...")

&#x20; - \*\*Table data\*\* from HamBoneRaces' comment `body` (Reddit markdown table)

\- Downloads images to local `images/` directory

\- Strict rate limiting: 2-second delays between requests



\### Database (`database.py`)

\- SQLite database at `daily\_deals.db`

\- Table: `daily\_deals`

&#x20; - `id` (PK), `date\_key` (YYYYMMDD, UNIQUE), `title`, `image\_path`, `table\_data` (JSON), `reddit\_post\_id`, `reddit\_url`, `created\_at`



\### Telegram Bot (`bot.py`)

\- Uses `python-telegram-bot` (async, ApplicationBuilder pattern)

\- \*\*Commands:\*\*

&#x20; - `!MTGAStore` — Posts the most recent daily deal (image + formatted table)

&#x20; - `!MTGAStore YYYYMMDD` — Posts a specific day's deal

\- \*\*Scheduler:\*\*

&#x20; - Runs scraping every 6 hours (configurable via `SCRAPE\_INTERVAL\_HOURS` in `.env`)

&#x20; - Uses `APScheduler` integration built into `python-telegram-bot`



\### Telegram Message Formatting

\- Sends the deal image as a photo

\- Formats the table using Telegram's HTML or Markdown:

&#x20; ```

&#x20; 📅 Daily Deals - April 20, 2026



&#x20; Card Style      | Gems  | Gold

&#x20; Draft Token      | 1,350 | 9,000

&#x20; Riling Dawnbreaker| 50   | 250

&#x20; ...

&#x20; ```



\## Verification Plan



\### Manual Verification

1\. Run `python scraper.py` standalone to verify scraping works

2\. Verify SQLite database is populated correctly

3\. Run bot, send `!MTGAStore` in Telegram, confirm image + table is posted



