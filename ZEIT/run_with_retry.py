"""Run scraper with retry until login is successful."""
import sys
import time
import os
from dotenv import load_dotenv
from scraper import ArticleScraper
from check_status import check_status

load_dotenv()

def run_with_retry(max_attempts=5):
    """Run scraper with retry until login succeeds."""
    base_url = "https://www.zeit.de"
    login_url = "https://www.zeit.de/account/login"
    articles_url = "https://www.zeit.de/index"
    
    print("="*70)
    print("Running Scraper with Retry Until Login Success")
    print("="*70)
    print(f"Target: {base_url}")
    print(f"Max attempts: {max_attempts}")
    print("="*70)
    
    for attempt in range(1, max_attempts + 1):
        print(f"\n[Attempt {attempt}/{max_attempts}]")
        print("-"*70)
        
        try:
            scraper = ArticleScraper(base_url=base_url, login_url=login_url)
            scraper.setup_driver(headless=False)  # Keep visible for debugging
            
            # Try to login
            print("\nAttempting login...")
            login_success = scraper.login()
            
            if login_success:
                print("\n[SUCCESS] Login successful!")
                print("-"*70)
                
                # Navigate to articles page and scrape
                print(f"\nNavigating to articles page: {articles_url}")
                articles = scraper.get_article_list(articles_url)
                
                if articles:
                    print(f"\nFound {len(articles)} articles to scrape")
                    
                    # Get already scraped IDs
                    scraped_ids = scraper.db.get_all_scraped_ids()
                    new_articles = [a for a in articles if a['id'] not in scraped_ids]
                    print(f"New articles to scrape: {len(new_articles)}")
                    
                    # Scrape articles
                    successful = 0
                    failed = 0
                    
                    for idx, article in enumerate(new_articles[:10], 1):  # Limit to 10 for testing
                        print(f"\n[{idx}/{len(new_articles[:10])}] Scraping: {article.get('title', article['url'])}")
                        try:
                            article_data = scraper.scrape_article(article['url'], article['id'])
                            if article_data and article_data.get('content'):
                                scraper.db.save_article(
                                    article_id=article_data['id'],
                                    title=article_data['title'],
                                    content=article_data['content'],
                                    tags=article_data.get('tags', []),
                                    article_url=article_data['url'],
                                    article_date=article_data.get('article_date'),
                                    article_updated=article_data.get('article_updated'),
                                    source=article_data.get('source'),
                                    scraped_at=article_data.get('scraped_at')
                                )
                                successful += 1
                                print(f"  [OK] Saved: {article_data['title'][:50]}...")
                            else:
                                failed += 1
                                print(f"  [X] Failed to scrape")
                        except Exception as e:
                            failed += 1
                            print(f"  [ERROR] {str(e)}")
                    
                    print(f"\n[SUMMARY] Successful: {successful}, Failed: {failed}")
                    
                    # Check final status
                    print("\n" + "="*70)
                    print("Final Status Check")
                    print("="*70)
                    check_status()
                    
                else:
                    print("\n[WARNING] No articles found")
                
                scraper.cleanup()
                return True
            else:
                print(f"\n[FAILED] Login unsuccessful on attempt {attempt}")
                scraper.cleanup()
                
                if attempt < max_attempts:
                    wait_time = 5 * attempt
                    print(f"\nWaiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                
        except Exception as e:
            print(f"\n[ERROR] Attempt {attempt} failed: {str(e)}")
            import traceback
            traceback.print_exc()
            
            if attempt < max_attempts:
                wait_time = 5 * attempt
                print(f"\nWaiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
    
    print("\n" + "="*70)
    print("[FAILED] All login attempts exhausted")
    print("="*70)
    return False

if __name__ == "__main__":
    success = run_with_retry(max_attempts=5)
    sys.exit(0 if success else 1)

