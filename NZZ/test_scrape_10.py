"""Test script to scrape 10 articles and save to JSON."""
import json
import os
from datetime import datetime
from scraper import NZZScraper

# Get the directory where this script is located (NZZ folder)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def main():
    """Scrape 10 articles and save to JSON."""
    print("="*80)
    print("TEST: Scraping 10 NZZ Articles")
    print("="*80)
    
    scraper = NZZScraper()
    
    try:
        # Get article list (stop after 10 articles)
        print("\n[1/3] Getting article list (stopping after 10 articles)...")
        print("Note: This will open a browser and scroll to collect articles...")
        
        # Get article list with max limit of 10 (skip batch scraping for test)
        # We'll manually scrape them after getting the list
        articles = scraper.get_article_list(max_articles=10)
        
        if not articles:
            print("No articles found!")
            return
        
        # Use the articles we got (should be 10 or less)
        test_articles = articles[:10]
        print(f"\nCollected {len(test_articles)} articles for testing")
        
        # Scrape the 10 articles manually (not through batch scraping)
        print(f"\n[2/3] Scraping {len(test_articles)} articles...")
        scraped_data = []
        
        for idx, article in enumerate(test_articles, 1):
            article_id = article.get('id')
            article_url = article.get('url')
            article_title = article.get('title', 'Untitled')
            
            print(f"\n[{idx}/{len(test_articles)}] Scraping: {article_title[:60]}...")
            
            try:
                article_data = scraper.scrape_article(article_url, article_id)
                if article_data:
                    # Convert datetime objects to strings for JSON
                    json_data = {
                        'id': article_data.get('id'),
                        'title': article_data.get('title'),
                        'url': article_data.get('url'),
                        'content': article_data.get('content'),
                        'content_length': len(article_data.get('content', '')),
                        'tags': article_data.get('tags', []),
                        'category': article_data.get('category'),
                        'author': article_data.get('author'),
                        'description': article_data.get('description'),
                        'article_date': article_data.get('article_date').isoformat() if article_data.get('article_date') else None,
                        'article_updated': article_data.get('article_updated').isoformat() if article_data.get('article_updated') else None,
                        'scraped_at': article_data.get('scraped_at').isoformat() if article_data.get('scraped_at') else None,
                    }
                    scraped_data.append(json_data)
                    print(f"  [OK] Successfully scraped")
                else:
                    print(f"  [FAIL] Failed to scrape (no data returned)")
            except Exception as e:
                print(f"  [ERROR] Error: {str(e)}")
        
        # Save to JSON file
        print(f"\n[3/3] Saving {len(scraped_data)} articles to JSON...")
        output_file = os.path.join(SCRIPT_DIR, 'test_10_articles.json')
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(scraped_data, f, indent=2, ensure_ascii=False)
        
        print(f"\n[OK] Successfully saved {len(scraped_data)} articles to: {output_file}")
        print(f"\nSummary:")
        print(f"  - Articles scraped: {len(scraped_data)}")
        print(f"  - Output file: {output_file}")
        print(f"  - File size: {os.path.getsize(output_file) / 1024:.2f} KB")
        
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

