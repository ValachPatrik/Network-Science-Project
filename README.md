# Web Scraper Project

This project contains scrapers for extracting articles from news websites.

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

The NZZ scraper will:
- Automatically handle cookie consent
- Login with your credentials
- Navigate to https://www.zeit.de/news/index
- Extract all articles
- Save to `scraped_articles.db`



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
python run_scraper_v3.py
```

The scraper will:
- Navigate to https://www.nzz.ch/neueste-artikel
- Extract all articles, authors from impressum

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

#### Core Fields

- **article_id**: Unique article identifier
- **title**: Article title
- **content**: Full text content of the article
- **article_url**: Source URL for the article (metadata)
- **description**: Article description/summary
- **tags**: Tags embedded within the article page
- **category**: URL category the article is assigned into (e.g., zuerich, wirtschaft, international)
- **article_date**: Release/publication date of the article
- **article_updated**: Latest update date (if article was edited)
- **scraped_at**: Timestamp when article was downloaded (metadata)

#### Author-Related Fields

- **author**: Raw author line containing author names, potentially with location and department information (needs processing)
- **authors**: List of author names extracted from the authors table
- **department**: List of author departments extracted from the authors table
- **location**: List of author locations extracted from the authors table
- **author_links**: Embedded links to author pages (if author is listed in impressum)

#### Network Analysis Fields

- **related_articles**: List of recommended related articles by NZZ (article IDs)
- **related_articles_filtered**: Filtered list containing only related articles that have been scraped, processed, and are within the one-year timeframe

#### Data Statistics

- **Total Articles**: 16,417 articles scraped
- **Timeframe**: Up to one year of article history
- **Data Sources**:
  - Article history page (endlessly scrollable)
  - Related articles from each article page

### NZZ Authors

Authors are sourced from the NZZ impressum page, which contains detailed information about employed authors. Note that NZZ employs many authors on a freelance/non-permanent basis, so the impressum list serves as enrichment data rather than a complete author dataset.

#### Core Fields

- **author_id**: Unique identifier assigned to authors in impressum (also referenced in articles)
- **name**: Author's full name (includes first, middle, and last names)
- **title**: Author's title/position within the firm (e.g., Chefredaktor, Stellvertretender Chefredaktor)
- **alt_name**: Shortcuts or initials used by NZZ to identify authors (e.g., "eg.", "daw.", "mij.")
- **bio**: Biography of the author
- **author_url**: Source URL from impressum page (metadata for potential further processing)
- **alias**: Potential aliases for author names to allow mapping even when string representations differ (e.g., "Eric Gujer (eg.)")
- **has_info**: Flag indicating whether author has bio and other information present from impressum (useful when processing authors from articles)

#### Organizational Fields

- **department**: Teams/departments authors are grouped into (e.g., International, Wochenende/Gesellschaft/Reisen)

#### Enrichment Fields

- **location**: Location data mapped from articles (potentially finding new insights)
- **tags**: Tag data mapped from articles (potentially finding new insights)
- **scraped_at**: Timestamp when author data was scraped (metadata)

#### Data Statistics

- **Total Authors**: 342 authors from impressum
- **Data Source**: NZZ impressum page
- **Note**: The impressum list is incomplete as many authors work on a freelance/non-permanent basis. Throughout the project, authors are primarily sourced from articles, with impressum data used for enrichment.

## Logs

- **ZEIT**: `ZEIT/scraper.log`
- **NZZ**: `NZZ/nzz_scraper.log`

## Build Graph and analye it
**Examples:**
```bash
# Install uv if not already installed
pip install uv

# to sync the project
uv sync

# Visualiztion of combined graph in sum mode
uv run NZZ/analysis/main.py analyser --visualize --no-largest-component --no-show-names

# Visualization of largest connected component and clustering with analysis.
uv run NZZ/analysis/main.py analyser --visualize --analyze --cluster louvain --no-show-names --impressum {path to the nzz_impressum.csv file}
```
Then, use the filtered_clustered_authors.csv file and do a pivot with the following settings:
Filters: Cluster
Column Fields: Data, and Row Fields: Role, and Data Fields: Count-Role. Also, see the provided filtered_clustered_authors.osd file,
and the Pivot Table_filtered_clustered_authors_1_2 tab. Different filtering was used to get all tables in the report.

The file "author_section_counts.csv" shows the mapping between articles and their authors. The count is the number of times different articles appear in that resort.

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
- Articles are stored in SQLite databases then migrated to supabase where we prvide cretentials for, in case the instance is inactive, please contact the creators.

