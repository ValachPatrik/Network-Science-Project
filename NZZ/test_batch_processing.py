"""Test script to verify batch processing with first 100 articles."""
import os
import sys
from scraper import NZZScraper

# Get the directory where this script is located (NZZ folder)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def main():
    """Test batch processing with first 100 articles."""
    print("="*80)
    print("TEST: Batch Processing with First 100 Articles")
    print("="*80)
    print("Testing:")
    print("  - 1 day limit (instead of 1 year)")
    print("  - Batch processing every 50 articles")
    print("  - First 100 articles only")
    print("="*80)
    
    scraper = NZZScraper()
    
    try:
        # Get article list (stop after 100 articles)
        print("\n[1/2] Getting article list (stopping after 100 articles)...")
        print("Note: This will open a browser and scroll to collect articles...")
        
        # Get article list with max limit of 100
        articles = scraper.get_article_list(max_articles=100)
        
        if not articles:
            print("No articles found!")
            return
        
        print(f"\nCollected {len(articles)} articles for testing")
        print(f"\n[2/2] Batch processing should have happened during collection")
        print("Checking database for scraped articles...")
        
        # Check database
        from database import DatabaseManager
        db = DatabaseManager()
        total_in_db = db.get_article_count()
        db.close()
        
        print(f"\nResults:")
        print(f"  - Articles collected: {len(articles)}")
        print(f"  - Articles in database: {total_in_db}")
        print(f"  - Expected batches: {len(articles) // 50} (every 50 articles)")
        
        if total_in_db > 0:
            print(f"\n[OK] Batch processing is working! Found {total_in_db} articles in database.")
        else:
            print(f"\n[WARNING] No articles found in database. Batch processing may not have triggered.")
        
    except Exception as e:
        print(f"\n[ERROR] Error: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        scraper.cleanup()
        print("\n" + "="*80)
        print("Test complete!")
        print("="*80)

if __name__ == '__main__':
    main()

