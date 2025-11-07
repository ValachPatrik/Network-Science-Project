"""Simple script to run the article scraper."""
import sys
import os
from scraper import ArticleScraper

if __name__ == "__main__":
    # Check if environment variables are set
    mail = os.getenv('MAIL')
    pass_env = os.getenv('PASS')
    
    if not mail or not pass_env:
        print("Error: MAIL and PASS environment variables must be set")
        print("Please create a .env file with your credentials:")
        print("MAIL=your_email@example.com")
        print("PASS=your_password")
        sys.exit(1)
    
    # Get website URL from command line or use default
    if len(sys.argv) < 2:
        print("Usage: python run_scraper.py <base_url> [--login-url LOGIN_URL] [--articles-url ARTICLES_URL] [--headless]")
        print("\nExample:")
        print("  python run_scraper.py https://example.com")
        print("  python run_scraper.py https://example.com --login-url https://example.com/login --articles-url https://example.com/articles --headless")
        sys.exit(1)
    
    base_url = sys.argv[1]
    login_url = None
    articles_url = None
    headless = False
    
    # Parse command line arguments
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == '--login-url' and i + 1 < len(sys.argv):
            login_url = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--articles-url' and i + 1 < len(sys.argv):
            articles_url = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--headless':
            headless = True
            i += 1
        else:
            i += 1
    
    # Create and run scraper
    scraper = ArticleScraper(base_url=base_url, login_url=login_url)
    scraper.run(articles_url=articles_url, headless=headless)

