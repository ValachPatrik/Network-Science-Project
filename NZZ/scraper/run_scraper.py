"""Script to run the NZZ scraper."""

import sys
from scraper import NZZScraper

if __name__ == "__main__":
    scraper = NZZScraper()
    scraper.run()
