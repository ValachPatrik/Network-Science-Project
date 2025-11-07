# ZEIT.de Article Scraper

Scraper for extracting articles from https://www.zeit.de/news/index

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r ../requirements.txt
   ```

2. **Create `.env` file in project root:**
   ```
   MAIL=your_email@example.com
   PASS=your_password
   ```

## Running the Scraper

### Basic Usage

```bash
python run_scraper.py
```

### With Custom URLs

```bash
python run_and_verify.py https://www.zeit.de --login-url https://www.zeit.de/account/login --articles-url https://www.zeit.de/news/index
```

### Run with Retry (if login fails)

```bash
python run_with_retry.py
```

## Viewing Scraped Articles

### DataFrame View (Recommended)

```bash
# Show all articles
python view_articles.py df

# Show first 10 articles
python view_articles.py df --limit 10

# Show specific article
python view_articles.py df --id article-id-here

# Search articles
python view_articles.py df --search "politics"
```

### Detailed View

```bash
# View all articles in detail
python view_articles.py view

# View first 5 articles
python view_articles.py view --limit 5

# View specific article
python view_articles.py view --id article-id-here
```

### Summary View

```bash
python view_articles.py list
```

## Check Status

```bash
python check_status.py
```

## Verify Articles

```bash
python verify_scraper.py
```

## Features

- Automatic cookie consent handling
- Automatic login with credentials
- Handles Keycloak/OpenID Connect login
- Extracts articles from news index page
- Extracts tags from article-tags__list structure
- Extracts source from metadata__source span
- Extracts publication date from metadata__date time element
- Removes " | DIE ZEIT" from titles
- Rate limiting and retry logic
- Infinite scroll and pagination support

## Database

Articles are stored in `scraped_articles.db` SQLite database.

## Logs

Check `scraper.log` for detailed operation logs.


