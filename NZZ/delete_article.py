"""Script to delete articles from the NZZ database by article ID."""
import sys
import os
import argparse
from database import DatabaseManager

# Get the directory where this script is located (NZZ folder)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def delete_article_by_id(article_id: str, show_info: bool = True, confirm: bool = True) -> bool:
    """Delete an article by its ID.
    
    Args:
        article_id: The article ID to delete
        show_info: Whether to show article information before deletion
        confirm: Whether to ask for confirmation
    
    Returns:
        bool: True if article was deleted, False if not found or cancelled
    """
    db = DatabaseManager()
    
    try:
        # Get article information
        article = db.get_article_by_id(article_id)
        
        if not article:
            print(f"[X] Article with ID '{article_id}' not found in database.")
            return False
        
        # Show article information
        if show_info:
            print("="*80)
            print("ARTICLE TO DELETE")
            print("="*80)
            print(f"ID: {article.article_id}")
            print(f"Title: {article.title or 'Untitled'}")
            print(f"URL: {article.article_url}")
            if article.category:
                print(f"Category: {article.category}")
            if article.author:
                print(f"Author: {article.author}")
            if article.article_date:
                print(f"Published: {article.article_date.strftime('%Y-%m-%d %H:%M:%S')}")
            print("="*80)
        
        # Confirm deletion
        if confirm:
            response = input(f"\nAre you sure you want to delete article '{article_id}'? (yes/no): ").strip().lower()
            if response not in ['yes', 'y']:
                print("Operation cancelled.")
                return False
        
        # Delete article
        success = db.delete_article_by_id(article_id)
        
        if success:
            print(f"\n[OK] Article '{article_id}' deleted successfully.")
            return True
        else:
            print(f"\n[X] Failed to delete article '{article_id}'.")
            return False
        
    except Exception as e:
        print(f"\n[X] Error deleting article: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def delete_articles_by_ids(article_ids: list, show_info: bool = True, confirm: bool = True) -> int:
    """Delete multiple articles by their IDs.
    
    Args:
        article_ids: List of article IDs to delete
        show_info: Whether to show article information before deletion
        confirm: Whether to ask for confirmation
    
    Returns:
        int: Number of articles deleted
    """
    db = DatabaseManager()
    
    try:
        if not article_ids:
            print("[!] No article IDs provided.")
            return 0
        
        # Get articles information
        articles = []
        not_found = []
        
        for article_id in article_ids:
            article = db.get_article_by_id(article_id)
            if article:
                articles.append(article)
            else:
                not_found.append(article_id)
        
        # Show not found articles
        if not_found:
            print(f"\n[!] {len(not_found)} article(s) not found:")
            for article_id in not_found:
                print(f"  - {article_id}")
        
        if not articles:
            print("\n[!] No articles found to delete.")
            return 0
        
        # Show articles information
        if show_info:
            print("\n" + "="*80)
            print(f"ARTICLES TO DELETE ({len(articles)})")
            print("="*80)
            for idx, article in enumerate(articles, 1):
                print(f"\n{idx}. ID: {article.article_id}")
                print(f"   Title: {article.title or 'Untitled'}")
                if article.category:
                    print(f"   Category: {article.category}")
            print("="*80)
        
        # Confirm deletion
        if confirm:
            response = input(f"\nAre you sure you want to delete {len(articles)} article(s)? (yes/no): ").strip().lower()
            if response not in ['yes', 'y']:
                print("Operation cancelled.")
                return 0
        
        # Delete articles
        article_ids_to_delete = [a.article_id for a in articles]
        deleted_count = db.delete_articles_by_ids(article_ids_to_delete)
        
        print(f"\n[OK] {deleted_count} article(s) deleted successfully.")
        
        if not_found:
            print(f"[!] {len(not_found)} article(s) were not found and could not be deleted.")
        
        return deleted_count
        
    except Exception as e:
        print(f"\n[X] Error deleting articles: {str(e)}")
        import traceback
        traceback.print_exc()
        return 0
    finally:
        db.close()


def main():
    """Main function to handle command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Delete articles from the NZZ database by article ID',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Delete a single article (with confirmation)
  python delete_article.py 1671603
  
  # Delete a single article without confirmation
  python delete_article.py 1671603 --no-confirm
  
  # Delete multiple articles
  python delete_article.py 1671603 1861594 1882252
  
  # Delete articles from a file (one ID per line)
  python delete_article.py --file article_ids.txt
  
  # Delete without showing article information
  python delete_article.py 1671603 --no-info
        """
    )
    
    parser.add_argument('article_ids', nargs='*', metavar='ID',
                       help='Article ID(s) to delete')
    parser.add_argument('--file', '-f', type=str, metavar='FILE',
                       help='File containing article IDs (one per line)')
    parser.add_argument('--no-confirm', action='store_true',
                       help='Skip confirmation prompts (use with caution!)')
    parser.add_argument('--no-info', action='store_true',
                       help='Do not show article information before deletion')
    
    args = parser.parse_args()
    
    # Collect article IDs
    article_ids = list(args.article_ids) if args.article_ids else []
    
    # Read from file if provided
    if args.file:
        if not os.path.exists(args.file):
            print(f"[X] File '{args.file}' not found.", file=sys.stderr)
            sys.exit(1)
        
        try:
            with open(args.file, 'r', encoding='utf-8') as f:
                file_ids = [line.strip() for line in f if line.strip()]
                article_ids.extend(file_ids)
        except Exception as e:
            print(f"[X] Error reading file '{args.file}': {str(e)}", file=sys.stderr)
            sys.exit(1)
    
    # Check if any IDs provided
    if not article_ids:
        parser.print_help()
        print("\n[X] No article IDs provided. Use --help for usage information.", file=sys.stderr)
        sys.exit(1)
    
    # Remove duplicates
    article_ids = list(dict.fromkeys(article_ids))  # Preserve order while removing duplicates
    
    # Delete articles
    show_info = not args.no_info
    confirm = not args.no_confirm
    
    try:
        if len(article_ids) == 1:
            # Single article deletion
            success = delete_article_by_id(article_ids[0], show_info=show_info, confirm=confirm)
            sys.exit(0 if success else 1)
        else:
            # Multiple articles deletion
            deleted_count = delete_articles_by_ids(article_ids, show_info=show_info, confirm=confirm)
            sys.exit(0 if deleted_count > 0 else 1)
    
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n[X] Error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()







