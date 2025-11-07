"""Script to run scraper and verify results."""
import sys
import os
from dotenv import load_dotenv
from scraper import ArticleScraper
from verify_scraper import verify_articles

load_dotenv()

def run_and_verify(base_url: str, login_url: str = None, articles_url: str = None, headless: bool = False):
    """Run the scraper and verify results."""
    print("="*70)
    print("Running Article Scraper")
    print("="*70)
    
    # Check environment variables
    mail = os.getenv('MAIL')
    pass_env = os.getenv('PASS')
    
    if not mail or not pass_env:
        print("\n[ERROR] MAIL and PASS environment variables must be set!")
        print("Please create a .env file with your credentials:")
        print("MAIL=your_email@example.com")
        print("PASS=your_password")
        return False
    
        print(f"\nTarget Website: ZEIT.de")
        print(f"Base URL: {base_url}")
        if login_url:
            print(f"Login URL: {login_url}")
        if articles_url:
            print(f"Articles URL: {articles_url}")
        else:
            print(f"Articles URL: {base_url}/news/index (default)")
        print(f"Headless mode: {headless}")
        print(f"Credentials: {mail}")
        print("\n" + "-"*70)
    
    try:
        # Run scraper
        print("\n[1/2] Starting scraper...")
        scraper = ArticleScraper(base_url=base_url, login_url=login_url)
        scraper.run(articles_url=articles_url, headless=headless)
        print("\n[1/2] Scraper completed!")
        
        # Verify results
        print("\n" + "-"*70)
        print("\n[2/2] Verifying scraped articles...")
        success = verify_articles()
        
        if success:
            print("\n" + "="*70)
            print("[SUCCESS] Scraping and verification completed successfully!")
            print("="*70)
        else:
            print("\n" + "="*70)
            print("[WARNING] Scraping completed but verification found issues.")
            print("="*70)
        
        return success
        
    except KeyboardInterrupt:
        print("\n\n[INTERRUPTED] Scraping interrupted by user.")
        return False
    except Exception as e:
        print(f"\n[ERROR] Error during scraping: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_and_verify.py <base_url> [--login-url LOGIN_URL] [--articles-url ARTICLES_URL] [--headless]")
        print("\nExample:")
        print("  python run_and_verify.py https://example.com")
        print("  python run_and_verify.py https://example.com --login-url https://example.com/login --articles-url https://example.com/articles --headless")
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
    
    # Default to news/index if not specified
    if not articles_url:
        articles_url = f"{base_url}/news/index"
    
    success = run_and_verify(base_url, login_url, articles_url, headless)
    sys.exit(0 if success else 1)

