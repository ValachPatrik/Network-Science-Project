# Web Scraper Project

This project contains scrapers for extracting articles from news websites.

## Project Structure

```
projekt/
├── ZEIT/              # ZEIT.de scraper
│   ├── scraper.py     # Main scraper
│   ├── database.py    # Database models
│   ├── run_scraper.py # Run script
│   ├── view_articles.py # View scraped articles
│   ├── check_status.py # Check scraper status
│   └── verify_scraper.py # Verify articles
├── NZZ/               # NZZ.ch scraper
│   ├── scraper.py     # Main scraper
│   ├── database.py    # Database models
│   ├── run_scraper.py # Run script
│   ├── view_articles.py # View scraped articles
│   └── clean_db.py    # Database cleanup script
├── requirements.txt   # Python dependencies
├── README.md          # This file
└── QUICK_START.md     # Quick start guide
```

## Installation

1. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up environment variables (for ZEIT scraper only):**
   Create a `.env` file in the project root:
   ```
   MAIL=your_email@example.com
   PASS=your_password
   ```

## Quick Start

See [QUICK_START.md](QUICK_START.md) for a quick reference guide.

## Running the Scrapers

### ZEIT.de Scraper

The ZEIT scraper requires login credentials and uses Selenium for browser automation.

#### Step 1: Setup

1. Create `.env` file in project root:
   ```
   MAIL=your_email@example.com
   PASS=your_password
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

#### Step 2: Run the Scraper

```bash
cd ZEIT
python run_scraper.py
```

The scraper will:
- Automatically handle cookie consent
- Login with your credentials
- Navigate to https://www.zeit.de/news/index
- Extract all articles
- Save to `scraped_articles.db`

#### Step 3: View Scraped Articles

```bash
cd ZEIT
# Show all articles as DataFrame (recommended)
python view_articles.py df

# Show first 10 articles
python view_articles.py df --limit 10

# Show specific article
python view_articles.py df --id article-id-here

# Search articles
python view_articles.py df --search "politics"

# View detailed article information
python view_articles.py view --limit 5

# List summary
python view_articles.py list
```

#### Additional Commands

```bash
cd ZEIT
# Check scraper status
python check_status.py

# Verify articles format
python verify_scraper.py

# Run with retry (if login fails)
python run_with_retry.py
```

### NZZ.ch Scraper

The NZZ scraper uses requests and BeautifulSoup (no login required).

#### Step 1: Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

#### Step 2: Run the Scraper

```bash
cd NZZ
python run_scraper.py
```

The scraper will:
- Navigate to https://www.nzz.ch/neueste-artikel
- Extract all articles
- Save to `nzz_scraped_articles.db`

#### Step 3: View Scraped Articles

```bash
cd NZZ
# Show all articles as DataFrame (recommended)
python view_articles.py df

# Show first 10 articles
python view_articles.py df --limit 10

# Show specific article
python view_articles.py df --id article-id-here

# Search articles
python view_articles.py df --search "wirtschaft"

# View detailed article information
python view_articles.py view --limit 5

# List summary
python view_articles.py list
```

#### Step 4: Clean Database (Optional)

```bash
cd NZZ
# Show database statistics
python clean_db.py --stats

# Delete all articles (with confirmation)
python clean_db.py --delete-all

# Delete articles older than 30 days
python clean_db.py --delete-before-days 30

# Delete articles in a specific category
python clean_db.py --delete-category zuerich

# Delete duplicate articles (keep oldest)
python clean_db.py --delete-duplicates

# Reset entire database (drop and recreate tables)
python clean_db.py --reset

# Skip confirmation prompts (use with caution!)
python clean_db.py --delete-all --no-confirm
```

## Database Files

- **ZEIT**: `ZEIT/scraped_articles.db`
- **NZZ**: `NZZ/nzz_scraped_articles.db`

## Features

### ZEIT.de Scraper Features

- ✅ Automatic cookie consent handling
- ✅ Automatic login with credentials
- ✅ Handles Keycloak/OpenID Connect login
- ✅ Extracts articles from https://www.zeit.de/news/index
- ✅ Extracts tags from `<ul class="article-tags__list">`
- ✅ Extracts source from `<span class="metadata__source">`
- ✅ Extracts publication date from `<time class="metadata__date">`
- ✅ Removes " | DIE ZEIT" from titles
- ✅ Rate limiting and retry logic
- ✅ Infinite scroll and pagination support

### NZZ.ch Scraper Features

- ✅ Extracts articles from https://www.nzz.ch/neueste-artikel
- ✅ Extracts tags from `news_keywords` meta tag (Step 1)
- ✅ Filters out generic keywords (Step 2)
- ✅ Extracts category from URL path (Step 3)
- ✅ Extracts author, description, dates
- ✅ Rate limiting and retry logic

## Extracted Fields

### ZEIT.de Articles

- **ID**: Article ID
- **Title**: Article title (cleaned of " | DIE ZEIT")
- **URL**: Article URL
- **Content**: Full article content
- **Tags**: Tags from article-tags__list
- **Source**: Source/Quelle from metadata__source
- **Published**: Publication date
- **Updated**: Updated date (if available)
- **Scraped At**: Exact time when article was downloaded (down to second)

### NZZ Articles

- **ID**: Article ID (from URL pattern ld.XXXXX)
- **Title**: Article title
- **URL**: Article URL
- **Content**: Full article content
- **Tags**: Tags from news_keywords meta tag (filtered)
- **Category**: Category from URL path (e.g., zuerich, wirtschaft)
- **Author**: Author name
- **Description**: Article description
- **Published**: Publication date
- **Updated**: Updated date (if available)
- **Scraped At**: Exact time when article was downloaded (down to second)

## Viewing Articles

Both scrapers include a `view_articles.py` script that displays scraped articles in a DataFrame format.

### DataFrame View (Recommended)

The DataFrame view shows:
- **Total articles**: Number of articles in database
- **Number of datapoints**: Number of articles displayed
- **Number of columns**: Number of columns (11 for NZZ, 10 for ZEIT)
- **All columns**: Including **Content Length** (instead of actual content)

### Example Output

```
================================================================================
NZZ ARTICLES DATAFRAME
================================================================================
Total articles: 35
Number of datapoints: 35
Number of columns: 11

     ID    Title    URL    Category    Author    Tags    Description    Published    Updated    Scraped At    Content Length
...
```

### Available Commands

```bash
# Show all articles
python view_articles.py df

# Show first N articles
python view_articles.py df --limit 10

# Show specific article
python view_articles.py df --id article-id-here

# Search articles
python view_articles.py df --search "search-term"

# View detailed information
python view_articles.py view --limit 5

# List summary
python view_articles.py list
```

## Troubleshooting

### ZEIT Scraper Issues

1. **Login fails:**
   - Check your credentials in `.env` file
   - Ensure you have a valid ZEIT.de account
   - Check if the website structure has changed

2. **Cookie dialog not accepted:**
   - The scraper should handle this automatically
   - If it fails, check the logs in `scraper.log`

3. **Session invalid:**
   - The scraper includes retry logic
   - Check `scraper.log` for detailed error messages

### NZZ Scraper Issues

1. **No articles found:**
   - Check your internet connection
   - Verify the website is accessible
   - Check the logs for errors

2. **Content not extracted:**
   - Some articles may be behind a paywall
   - Check if the article structure has changed

## Database Management

### NZZ Database Cleanup

The NZZ scraper includes a `clean_db.py` script for managing the database:

**Available Operations:**
- `--stats`: Show database statistics (total articles, date range, categories)
- `--delete-all`: Delete all articles from the database
- `--delete-before-days N`: Delete articles scraped before N days ago
- `--delete-after-days N`: Delete articles scraped after N days ago
- `--delete-category CATEGORY`: Delete articles in a specific category
- `--delete-duplicates`: Delete duplicate articles (keeps the oldest version)
- `--reset`: Reset entire database (drops and recreates all tables)
- `--no-confirm`: Skip confirmation prompts (use with caution!)

**Examples:**
```bash
cd NZZ

# Show statistics
python clean_db.py --stats

# Delete all articles
python clean_db.py --delete-all

# Delete articles older than 30 days
python clean_db.py --delete-before-days 30

# Delete articles in 'zuerich' category
python clean_db.py --delete-category zuerich

# Delete duplicates
python clean_db.py --delete-duplicates

# Reset database
python clean_db.py --reset
```

## Logs

- **ZEIT**: `ZEIT/scraper.log`
- **NZZ**: `NZZ/nzz_scraper.log`

## Requirements

See `requirements.txt` for all dependencies:
- selenium>=4.15.0
- beautifulsoup4>=4.12.0
- python-dotenv>=1.0.0
- sqlalchemy>=2.0.0
- webdriver-manager>=4.0.0
- python-dateutil>=2.8.0
- pandas>=2.0.0

## Notes

- The ZEIT scraper requires Chrome/Chromium browser (managed by webdriver-manager)
- The NZZ scraper uses requests library (no browser needed)
- Both scrapers include rate limiting to be respectful to the servers
- Articles are stored in SQLite databases

