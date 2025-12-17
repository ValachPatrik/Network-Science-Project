"""Run NZZ scraper v3."""

from scraper_v3 import NZZScraperV3

if __name__ == "__main__":
    scraper = NZZScraperV3()
    # Set clean flags to True to clean tables before scraping, False to append
    scraper.run(
        headless=True,
        clean_authors_raw=False,  # Set to True to clean authors_raw table
        clean_articles_raw=False,  # Set to True to clean articles_raw table
    )
