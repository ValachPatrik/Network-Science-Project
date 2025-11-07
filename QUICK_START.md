# Quick Start Guide

## Installation

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **For ZEIT scraper only - Create `.env` file:**
   ```
   MAIL=your_email@example.com
   PASS=your_password
   ```

## Running the Scrapers

### ZEIT.de Scraper

```bash
cd ZEIT
python run_scraper.py
```

**View articles:**
```bash
cd ZEIT
python view_articles.py df
```

### NZZ.ch Scraper

```bash
cd NZZ
python run_scraper.py
```

**View articles:**
```bash
cd NZZ
python view_articles.py df
```

## Viewing Articles

Both scrapers support the same viewing commands:

```bash
# Show all articles as DataFrame
python view_articles.py df

# Show first 10 articles
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

## Output Format

The DataFrame view shows:
- **Total articles**: Number of articles in database
- **Number of datapoints**: Number of articles displayed
- **Number of columns**: Number of columns (11 for NZZ, 10 for ZEIT)
- **All columns**: Including **Content Length** (instead of actual content)

## Database Files

- **ZEIT**: `ZEIT/scraped_articles.db`
- **NZZ**: `NZZ/nzz_scraped_articles.db`

## Logs

- **ZEIT**: `ZEIT/scraper.log`
- **NZZ**: `NZZ/nzz_scraper.log`


