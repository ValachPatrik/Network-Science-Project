"""Script to verify scraped articles are saved correctly."""
import sys
from database import DatabaseManager

def verify_articles():
    """Verify that articles are saved in proper format."""
    db = DatabaseManager()
    
    try:
        total_count = db.get_article_count()
        print(f"\n{'='*60}")
        print(f"Article Verification Report")
        print(f"{'='*60}")
        print(f"Total articles in database: {total_count}")
        
        if total_count == 0:
            print("\n[!] No articles found in database.")
            print("Run the scraper first to populate the database.")
            return False
        
        articles = db.get_all_articles()
        valid_count = 0
        invalid_count = 0
        
        print(f"\nVerifying {len(articles)} articles...")
        print(f"{'-'*60}")
        
        for idx, article in enumerate(articles[:10], 1):  # Check first 10
            checks = db.verify_article_format(article)
            
            if checks['all_valid']:
                valid_count += 1
                status = "[OK] VALID"
            else:
                invalid_count += 1
                status = "[X] INVALID"
                missing = [k.replace('has_', '') for k, v in checks.items() if not v and k != 'all_valid']
            
            print(f"\nArticle {idx}: {status}")
            print(f"  ID: {article.article_id}")
            print(f"  Title: {article.title[:60] if article.title else 'N/A'}...")
            print(f"  URL: {article.article_url}")
            print(f"  Content length: {len(article.content) if article.content else 0} characters")
            print(f"  Tags: {article.tags if article.tags else 'None'}")
            print(f"  Scraped at: {article.scraped_at}")
            print(f"  Article date: {article.article_date if article.article_date else 'N/A'}")
            
            if not checks['all_valid']:
                print(f"  Missing/invalid: {', '.join(missing)}")
        
        if len(articles) > 10:
            print(f"\n... (showing first 10 of {len(articles)} articles)")
        
        # Check all articles for format
        all_valid = 0
        all_invalid = 0
        for article in articles:
            checks = db.verify_article_format(article)
            if checks['all_valid']:
                all_valid += 1
            else:
                all_invalid += 1
        
        print(f"\n{'-'*60}")
        print(f"Summary:")
        print(f"  Total articles: {total_count}")
        print(f"  Valid format: {all_valid}")
        print(f"  Invalid format: {all_invalid}")
        print(f"{'='*60}\n")
        
        return all_invalid == 0
        
    except Exception as e:
        print(f"\n[X] Error verifying articles: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


if __name__ == "__main__":
    success = verify_articles()
    sys.exit(0 if success else 1)

