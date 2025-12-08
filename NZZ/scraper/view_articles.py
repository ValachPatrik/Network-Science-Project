"""Script to view scraped NZZ articles from the database."""
import sys
import os
import pandas as pd
from datetime import datetime, timedelta
from collections import defaultdict
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
            # Show oldest article date
            oldest_date = db.get_oldest_article_date()
            if oldest_date:
                print(f"Oldest article date: {oldest_date.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}\n")
        
    except Exception as e:
        print(f"\n[X] Error viewing articles: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def show_oldest_article_date():
    """Display the oldest article date from the database."""
    db = DatabaseManager()
    
    try:
        total_count = db.get_article_count()
        
        print("="*80)
        print("OLDEST ARTICLE DATE")
        print("="*80)
        print(f"Total articles in database: {total_count}\n")
        
        if total_count == 0:
            print("[!] No articles found in database.")
            print("Run the scraper first to populate the database.")
            return
        
        oldest_date = db.get_oldest_article_date()
        
        if oldest_date:
            print(f"Oldest article date: {oldest_date.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Formatted: {oldest_date.strftime('%B %d, %Y at %H:%M:%S')}")
            
            # Calculate days ago
            days_ago = (datetime.now() - oldest_date).days
            print(f"Days ago: {days_ago}")
        else:
            print("[!] No articles with article_date found in database.")
            print("Some articles may not have publication dates.")
        
        print("="*80 + "\n")
        
    except Exception as e:
        print(f"\n[X] Error getting oldest article date: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def show_top_oldest_articles(limit: int = 10):
    """Display the top N oldest articles from the database."""
    db = DatabaseManager()
    
    try:
        total_count = db.get_article_count()
        
        print("="*80)
        print(f"TOP {limit} OLDEST ARTICLES")
        print("="*80)
        print(f"Total articles in database: {total_count}\n")
        
        if total_count == 0:
            print("[!] No articles found in database.")
            print("Run the scraper first to populate the database.")
            return
        
        # Get oldest articles
        oldest_articles = db.get_oldest_articles(limit=limit)
        
        if not oldest_articles:
            print("[!] No articles with article_date found in database.")
            print("Some articles may not have publication dates.")
            return
        
        print(f"Found {len(oldest_articles)} article(s) with dates\n")
        print("-"*80)
        
        # Display articles
        for idx, article in enumerate(oldest_articles, 1):
            print(f"\n{'='*80}")
            print(f"#{idx} - OLDEST ARTICLE (ID: {article.article_id})")
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
            
            # Author
            if article.author:
                print(f"\nAUTHOR:")
                print(f"  {article.author}")
            
            # Article Date (most important for oldest articles)
            print(f"\nPUBLISHED DATE:")
            if article.article_date:
                print(f"  {article.article_date.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"  {article.article_date.strftime('%B %d, %Y at %H:%M:%S')}")
                days_ago = (datetime.now() - article.article_date).days
                print(f"  ({days_ago} days ago)")
            else:
                print(f"  Not available")
            
            # Tags
            if article.tags:
                tags_list = [t.strip() for t in article.tags.split(',') if t.strip()]
                print(f"\nTAGS ({len(tags_list)}):")
                print(f"  {', '.join(tags_list) if tags_list else 'None'}")
            
            # Description
            if article.description:
                print(f"\nDESCRIPTION:")
                print(f"  {article.description[:200]}..." if len(article.description) > 200 else f"  {article.description}")
            
            # Content Length
            print(f"\nCONTENT:")
            content_length = len(article.content) if article.content else 0
            print(f"  Length: {content_length} characters")
        
        print(f"\n{'='*80}")
        print(f"Total displayed: {len(oldest_articles)}")
        print(f"{'='*80}\n")
        
    except Exception as e:
        print(f"\n[X] Error getting oldest articles: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def show_articles_per_day_histogram():
    """Display a histogram showing the number of articles per day."""
    db = DatabaseManager()
    
    try:
        total_count = db.get_article_count()
        
        print("="*80)
        print("ARTICLES PER DAY HISTOGRAM")
        print("="*80)
        print(f"Total articles in database: {total_count}\n")
        
        if total_count == 0:
            print("[!] No articles found in database.")
            print("Run the scraper first to populate the database.")
            return
        
        # Get all articles with dates
        articles = db.get_all_articles()
        articles_with_dates = [a for a in articles if a.article_date]
        
        if not articles_with_dates:
            print("[!] No articles with article_date found in database.")
            print("Some articles may not have publication dates.")
            return
        
        # Group articles by day
        articles_per_day = defaultdict(int)
        for article in articles_with_dates:
            # Use article_date (published date) for grouping
            day_key = article.article_date.date() if article.article_date else None
            if day_key:
                articles_per_day[day_key] += 1
        
        if not articles_per_day:
            print("[!] No valid dates found for grouping.")
            return
        
        # Sort by date
        sorted_days = sorted(articles_per_day.keys())
        
        # Print statistics
        print(f"Articles with dates: {len(articles_with_dates)}")
        print(f"Date range: {sorted_days[0]} to {sorted_days[-1]}")
        print(f"Total days: {len(sorted_days)}")
        print(f"Average articles per day: {len(articles_with_dates) / len(sorted_days):.2f}")
        print(f"Max articles in a day: {max(articles_per_day.values())}")
        print(f"Min articles in a day: {min(articles_per_day.values())}")
        print("\n" + "-"*80)
        
        # Try to create a visual histogram with matplotlib
        try:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
            from matplotlib import font_manager
            
            # Prepare data for plotting - convert date objects to datetime objects
            dates = [datetime.combine(date, datetime.min.time()) for date in sorted_days]
            counts = [articles_per_day[date] for date in sorted_days]
            
            # Create figure with appropriate size for half a year of data
            fig, ax = plt.subplots(figsize=(16, 6))
            
            # Create bar chart with proper datetime handling
            # Convert dates to matplotlib date numbers for proper bar width calculation
            date_nums = mdates.date2num(dates)
            width = 0.8  # Width in days
            
            ax.bar(date_nums, counts, width=width, align='edge', alpha=0.7, color='steelblue')
            
            # Format x-axis for dates
            # Use AutoDateLocator for better automatic date formatting
            ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            
            # Rotate x-axis labels
            plt.xticks(rotation=45, ha='right')
            
            # Labels and title
            ax.set_xlabel('Date', fontsize=12)
            ax.set_ylabel('Number of Articles', fontsize=12)
            ax.set_title('Articles Per Day (Histogram)', fontsize=14, fontweight='bold')
            ax.grid(True, alpha=0.3, axis='y')
            
            # Set y-axis to start at 0
            ax.set_ylim(bottom=0)
            
            # Adjust layout to prevent label cutoff
            plt.tight_layout()
            
            # Show the plot
            plt.show()
            
            print("\n[OK] Histogram displayed successfully.")
            
        except ImportError:
            # Fallback to text-based histogram if matplotlib is not available
            print("\n[!] matplotlib not available. Displaying text-based histogram:\n")
            
            # Find max count for scaling
            max_count = max(articles_per_day.values())
            max_bar_length = 60  # Maximum bar length in characters
            
            # Print histogram
            for date in sorted_days:
                count = articles_per_day[date]
                bar_length = int((count / max_count) * max_bar_length) if max_count > 0 else 0
                bar = '█' * bar_length
                print(f"{date.strftime('%Y-%m-%d')}: {count:4d} {bar}")
            
            print("\n" + "-"*80)
            print("Note: Install matplotlib for a visual histogram: pip install matplotlib")
        
        print("="*80 + "\n")
        
    except Exception as e:
        print(f"\n[X] Error creating histogram: {str(e)}")
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
        elif command == 'oldest' or command == 'oldest-date':
            show_oldest_article_date()
        elif command == 'oldest-articles' or command == 'top-oldest':
            # Parse limit if provided
            limit = 10
            i = 2
            while i < len(sys.argv):
                if sys.argv[i] == '--limit' and i + 1 < len(sys.argv):
                    limit = int(sys.argv[i + 1])
                    i += 2
                else:
                    i += 1
            show_top_oldest_articles(limit=limit)
        elif command == 'histogram' or command == 'hist':
            show_articles_per_day_histogram()
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
            print("  python view_articles.py oldest             - Show oldest article date")
            print("  python view_articles.py oldest-articles    - Show top 10 oldest articles")
            print("  python view_articles.py oldest-articles --limit N - Show top N oldest articles")
            print("  python view_articles.py histogram          - Show histogram of articles per day")
    else:
        # Default: show dataframe
        show_dataframe()

