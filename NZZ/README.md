# NZZ.ch Article Scraper

Scraper for extracting articles from https://www.nzz.ch/neueste-artikel

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r ../requirements.txt
   ```

## Running the Scraper

### Basic Usage

```bash
python run_scraper.py
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
python view_articles.py df --search "wirtschaft"
```

The DataFrame view shows:
- **Total articles**: Number of articles in database
- **Number of datapoints**: Number of articles displayed
- **Number of columns**: Number of columns (11)
- **All columns**: ID, Title, URL, Category, Author, Tags, Description, Published, Updated, Scraped At, **Content Length** (instead of content)

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

## Tag Extraction (3 Steps)

1. **Step 1: Extract tags from `news_keywords` meta tag**
   - Splits comma-separated keywords from the `news_keywords` meta tag

2. **Step 2: Filter out generic keywords**
   - Removes: `Nachrichten`, `NZZ`, `News`, `Article`

3. **Step 3: Extract category from URL path**
   - Extracts category from URL structure (e.g., `/zuerich/`, `/wirtschaft/`, `/international/`)

## Features

- Extracts articles from neueste-artikel page
- Extracts tags from news_keywords meta tag (filtered)
- Extracts category from URL path
- Extracts author, description, dates
- Rate limiting and retry logic
- No login required

## Database

Articles are stored in `nzz_scraped_articles.db` SQLite database.

## Logs

Log files are saved in the `log/` subfolder:
- `nzz_scraper_YYYYMMDD_HHMMSS.log` - Main operation logs
- `nzz_scraper_errors_YYYYMMDD_HHMMSS.log` - Error logs only

## Documentation

- **SETUP.md** - Installation and Ollama setup
- **AUTHOR_PARSING.md** - Author parsing and normalization details
- **FIXES_SUMMARY.md** - Recent fixes and improvements
- **LLM_CALL_ANALYSIS.md** - LLM integration analysis

## Debug Scripts

Debug and test scripts are located in the `debug/` folder:
- `test_1000_authors.py` - Large-scale author parsing test
- `test_50_authors.py` - Smaller test
- Other test and analysis scripts

## Network Analysis Baselines

- `random_multilayer_baseline.py` builds a three-layer random author network that preserves the empirical degree of every author. Run it with `python -m NZZ.random_multilayer_baseline --limit 500 --top-k 15` to generate a baseline activity ranking, inspect the summaries printed to stdout, and optionally export the layers as GEXF for Gephi. Pass `--run-baseline` to `author_network.py` if you want that comparison to run automatically after building the empirical multilayer graph.
