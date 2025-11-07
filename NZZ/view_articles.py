"""Script to view scraped NZZ articles from the database."""
import sys
import os
import pandas as pd
from database import DatabaseManager

# Get the directory where this script is located (NZZ folder)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def view_articles(limit: int = None, article_id: str = None, search: str = None):
    """View scraped articles."""
    # DatabaseManager will automatically use NZZ folder path
    db = DatabaseManager()
    
    try:
        total_count = db.get_article_count()
        
        print("="*80)
        print("SCRAPED NZZ ARTICLES VIEWER")
        print("="*80)
        print(f"Total articles in database: {total_count}\n")
        
        if total_count == 0:
            print("[!] No articles found in database.")
            print("Run the scraper first to populate the database.")
            return
        
        # Get articles
        if article_id:
            articles = [a for a in db.get_all_articles() if a.article_id == article_id]
            if not articles:
                print(f"[X] Article with ID '{article_id}' not found.")
                return
        elif search:
            search_lower = search.lower()
            articles = [
                a for a in db.get_all_articles() 
                if search_lower in (a.title or '').lower() or 
                   search_lower in (a.content or '').lower() or
                   search_lower in (a.article_url or '').lower() or
                   search_lower in (a.category or '').lower() or
                   search_lower in (a.author or '').lower()
            ]
            if not articles:
                print(f"[X] No articles found matching '{search}'.")
                return
        else:
            articles = db.get_all_articles()
        
        # Apply limit
        if limit:
            articles = articles[:limit]
        
        print(f"Displaying {len(articles)} article(s)\n")
        print("-"*80)
        
        # Display articles
        for idx, article in enumerate(articles, 1):
            print(f"\n{'='*80}")
            print(f"ARTICLE #{idx} (ID: {article.article_id})")
            print(f"{'='*80}")
            
            # Title
            print(f"\nTITLE:")
            print(f"  {article.title or 'Untitled'}")
            
            # URL
            print(f"\nURL:")
            print(f"  {article.article_url}")
            
            # Category
            if article.category:
                print(f"\nCATEGORY:")
                print(f"  {article.category}")
            else:
                print(f"\nCATEGORY: Not available")
            
            # Author
            if article.author:
                print(f"\nAUTHOR:")
                print(f"  {article.author}")
            else:
                print(f"\nAUTHOR: Not available")
            
            # Tags
            if article.tags:
                tags_list = [t.strip() for t in article.tags.split(',') if t.strip()]
                print(f"\nTAGS ({len(tags_list)}):")
                print(f"  {', '.join(tags_list) if tags_list else 'None'}")
            else:
                print(f"\nTAGS: None")
            
            # Description
            if article.description:
                print(f"\nDESCRIPTION:")
                print(f"  {article.description[:200]}..." if len(article.description) > 200 else f"  {article.description}")
            else:
                print(f"\nDESCRIPTION: Not available")
            
            # Dates
            print(f"\nDATES:")
            if article.article_date:
                print(f"  Published: {article.article_date.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                print(f"  Published: Not available")
            if article.article_updated:
                print(f"  Updated: {article.article_updated.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  Scraped At: {article.scraped_at.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Content Length (instead of content)
            print(f"\nCONTENT:")
            content_length = len(article.content) if article.content else 0
            print(f"  Length: {content_length} characters")
            
            # Verification
            checks = db.verify_article_format(article)
            if checks['all_valid']:
                print(f"\n[OK] Article format: VALID")
            else:
                missing = [k.replace('has_', '') for k, v in checks.items() if not v and k != 'all_valid']
                print(f"\n[X] Article format: INVALID - Missing: {', '.join(missing)}")
        
        print(f"\n{'='*80}")
        print(f"Total displayed: {len(articles)}")
        if not limit and not article_id and not search:
            print(f"Total in database: {total_count}")
        print(f"{'='*80}\n")
        
    except Exception as e:
        print(f"\n[X] Error viewing articles: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def list_articles_summary():
    """List all articles in summary format."""
    db = DatabaseManager()
    
    try:
        articles = db.get_all_articles()
        total_count = len(articles)
        
        print("="*80)
        print("NZZ ARTICLES SUMMARY")
        print("="*80)
        print(f"Total articles: {total_count}\n")
        
        if total_count == 0:
            print("[!] No articles found in database.")
            return
        
        print(f"{'ID':<30} {'Title':<40} {'Category':<15} {'Date':<20} {'Status':<10}")
        print("-"*80)
        
        for article in articles:
            title_short = (article.title or 'Untitled')[:38]
            date_str = article.scraped_at.strftime('%Y-%m-%d') if article.scraped_at else 'N/A'
            category = article.category or 'N/A'
            checks = db.verify_article_format(article)
            status = "[OK]" if checks['all_valid'] else "[X]"
            
            print(f"{article.article_id[:28]:<30} {title_short:<40} {category[:13]:<15} {date_str:<20} {status:<10}")
        
        print("-"*80)
        print(f"Total: {total_count}\n")
        
    except Exception as e:
        print(f"\n[X] Error listing articles: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def show_dataframe(limit: int = None, article_id: str = None, search: str = None):
    """Display articles as a pandas DataFrame with content length instead of content."""
    # DatabaseManager will automatically use NZZ folder path
    db = DatabaseManager()
    
    try:
        total_count = db.get_article_count()
        
        if total_count == 0:
            print("[!] No articles found in database.")
            print("Run the scraper first to populate the database.")
            return
        
        # Get articles
        if article_id:
            articles = [a for a in db.get_all_articles() if a.article_id == article_id]
            if not articles:
                print(f"[X] Article with ID '{article_id}' not found.")
                return
        elif search:
            search_lower = search.lower()
            articles = [
                a for a in db.get_all_articles() 
                if search_lower in (a.title or '').lower() or 
                   search_lower in (a.content or '').lower() or
                   search_lower in (a.article_url or '').lower() or
                   search_lower in (a.category or '').lower() or
                   search_lower in (a.author or '').lower()
            ]
            if not articles:
                print(f"[X] No articles found matching '{search}'.")
                return
        else:
            articles = db.get_all_articles()
        
        # Apply limit
        if limit:
            articles = articles[:limit]
        
        # Prepare data for DataFrame
        data = []
        for article in articles:
            # Extract tags
            tags_list = []
            if article.tags:
                tags_list = [t.strip() for t in article.tags.split(',') if t.strip()]
            
            # Format dates
            published = article.article_date.strftime('%Y-%m-%d %H:%M:%S') if article.article_date else None
            updated = article.article_updated.strftime('%Y-%m-%d %H:%M:%S') if article.article_updated else None
            scraped = article.scraped_at.strftime('%Y-%m-%d %H:%M:%S') if article.scraped_at else None
            
            # Content length (instead of content)
            content_length = len(article.content) if article.content else 0
            
            # Description (truncated if too long)
            description = article.description[:100] + '...' if article.description and len(article.description) > 100 else article.description
            
            data.append({
                'ID': article.article_id,
                'Title': article.title or 'Untitled',
                'URL': article.article_url,
                'Category': article.category or None,
                'Author': article.author or None,
                'Tags': ', '.join(tags_list) if tags_list else None,
                'Description': description,
                'Published': published,
                'Updated': updated,
                'Scraped At': scraped,
                'Content Length': content_length,  # Content length instead of content
            })
        
        # Create DataFrame
        df = pd.DataFrame(data)
        
        # Display options
        pd.set_option('display.max_columns', None)
        pd.set_option('display.max_rows', None)
        pd.set_option('display.width', None)
        pd.set_option('display.max_colwidth', 100)
        
        print("="*80)
        print("NZZ ARTICLES DATAFRAME")
        print("="*80)
        print(f"Total articles: {len(df)}")
        print(f"Number of datapoints: {len(df)}")
        print(f"Number of columns: {len(df.columns)}\n")
        
        if len(df) > 0:
            print(df.to_string(index=False))
        else:
            print("[!] No articles to display.")
        
        print("\n" + "="*80)
        print(f"Total displayed: {len(df)}")
        if not limit and not article_id and not search:
            print(f"Total in database: {total_count}")
        print("="*80 + "\n")
        
    except Exception as e:
        print(f"\n[X] Error displaying dataframe: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == 'list' or command == 'summary':
            list_articles_summary()
        elif command == 'df' or command == 'dataframe':
            # Parse arguments for dataframe view
            limit = None
            article_id = None
            search = None
            
            i = 2
            while i < len(sys.argv):
                if sys.argv[i] == '--limit' and i + 1 < len(sys.argv):
                    limit = int(sys.argv[i + 1])
                    i += 2
                elif sys.argv[i] == '--id' and i + 1 < len(sys.argv):
                    article_id = sys.argv[i + 1]
                    i += 2
                elif sys.argv[i] == '--search' and i + 1 < len(sys.argv):
                    search = sys.argv[i + 1]
                    i += 2
                else:
                    i += 1
            
            show_dataframe(limit=limit, article_id=article_id, search=search)
        elif command == 'view' or command == 'show':
            # Parse arguments
            limit = None
            article_id = None
            search = None
            
            i = 2
            while i < len(sys.argv):
                if sys.argv[i] == '--limit' and i + 1 < len(sys.argv):
                    limit = int(sys.argv[i + 1])
                    i += 2
                elif sys.argv[i] == '--id' and i + 1 < len(sys.argv):
                    article_id = sys.argv[i + 1]
                    i += 2
                elif sys.argv[i] == '--search' and i + 1 < len(sys.argv):
                    search = sys.argv[i + 1]
                    i += 2
                else:
                    i += 1
            
            view_articles(limit=limit, article_id=article_id, search=search)
        else:
            print("Usage:")
            print("  python view_articles.py list              - List all articles in summary")
            print("  python view_articles.py df                - Show all articles as DataFrame")
            print("  python view_articles.py df --limit N      - Show first N articles as DataFrame")
            print("  python view_articles.py df --id ID         - Show specific article as DataFrame")
            print("  python view_articles.py df --search TERM   - Search articles and show as DataFrame")
            print("  python view_articles.py view               - View all articles in detail")
            print("  python view_articles.py view --limit N    - View first N articles")
            print("  python view_articles.py view --id ID       - View specific article by ID")
            print("  python view_articles.py view --search TERM - Search articles by term")
    else:
        # Default: show dataframe
        show_dataframe()

