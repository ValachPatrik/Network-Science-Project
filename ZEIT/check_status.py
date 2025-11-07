"""Quick script to check scraper status."""
import os
from database import DatabaseManager

def check_status():
    """Check scraper status."""
    print("="*70)
    print("Scraper Status Check")
    print("="*70)
    
    # Check log file
    log_exists = os.path.exists('scraper.log')
    print(f"\nLog file exists: {log_exists}")
    
    if log_exists:
        try:
            with open('scraper.log', 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                print(f"Log file size: {len(lines)} lines")
                if lines:
                    print("\nLast 10 log lines:")
                    print("-"*70)
                    for line in lines[-10:]:
                        print(line.rstrip())
        except Exception as e:
            print(f"Error reading log: {e}")
    
    # Check database
    db = DatabaseManager()
    try:
        count = db.get_article_count()
        print(f"\nArticles in database: {count}")
        
        if count > 0:
            articles = db.get_all_articles()
            print(f"\nLatest articles:")
            print("-"*70)
            for article in articles[:5]:
                print(f"  - {article.title[:60] if article.title else 'Untitled'}...")
                print(f"    URL: {article.article_url}")
                print(f"    Scraped: {article.scraped_at}")
    except Exception as e:
        print(f"Error checking database: {e}")
    finally:
        db.close()
    
    print("\n" + "="*70)

if __name__ == "__main__":
    check_status()

