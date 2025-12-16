"""Script to run the NZZ scraper v2."""

from scraper_v2 import NZZScraperV2

if __name__ == "__main__":
    scraper = NZZScraperV2()
    # Default to appending data (no cleanup)
    # Set individual clean flags to True to clean specific tables before scraping
    scraper.run(
        clean_articles=True,
        clean_authors=True,
        clean_related_articles=True,
        clean_article_author_associations=True,
    )
