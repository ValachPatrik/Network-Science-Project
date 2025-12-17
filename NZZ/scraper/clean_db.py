"""Script to clean/reset the NZZ database."""

import os
import sys
import argparse
from datetime import datetime, timedelta
from typing import Optional
from database import DatabaseManager, Article
from sqlalchemy import and_

# Get the directory where this script is located (NZZ folder)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def print_stats(db: DatabaseManager, label: str = "Current"):
    """Print database statistics."""
    count = db.get_article_count()
    print(f"\n{label} database statistics:")
    print(f"  Total articles: {count}")

    if count > 0:
        # Get date range
        articles = db.get_all_articles()
        dates = [a.scraped_at for a in articles if a.scraped_at]
        if dates:
            min_date = min(dates)
            max_date = max(dates)
            print(f"  Date range: {min_date} to {max_date}")

        # Get category distribution
        categories = {}
        for article in articles:
            cat = article.category or "None"
            categories[cat] = categories.get(cat, 0) + 1

        if categories:
            print(f"  Categories:")
            for cat, count in sorted(
                categories.items(), key=lambda x: x[1], reverse=True
            ):
                print(f"    {cat}: {count}")


def delete_all_articles(db: DatabaseManager, confirm: bool = True) -> int:
    """Delete all articles from the database."""
    count = db.get_article_count()

    if count == 0:
        print("Database is already empty.")
        return 0

    if confirm:
        print(f"\nWARNING: This will delete ALL {count} articles from the database!")
        response = (
            input("Are you sure you want to continue? (yes/no): ").strip().lower()
        )
        if response not in ["yes", "y"]:
            print("Operation cancelled.")
            return 0

    deleted = db.session.query(Article).delete()
    db.session.commit()
    print(f"\nDeleted {deleted} articles from the database.")
    return deleted


def delete_articles_by_date(
    db: DatabaseManager,
    before_date: Optional[datetime] = None,
    after_date: Optional[datetime] = None,
    confirm: bool = True,
) -> int:
    """Delete articles by date range."""
    query = db.session.query(Article)

    conditions = []
    if before_date:
        conditions.append(Article.scraped_at < before_date)
    if after_date:
        conditions.append(Article.scraped_at > after_date)

    if not conditions:
        print("No date filters specified.")
        return 0

    query = query.filter(and_(*conditions))
    count = query.count()

    if count == 0:
        print("No articles found matching the date criteria.")
        return 0

    if confirm:
        date_range = []
        if before_date:
            date_range.append(f"before {before_date}")
        if after_date:
            date_range.append(f"after {after_date}")
        print(f"\nWARNING: This will delete {count} articles {', '.join(date_range)}!")
        response = (
            input("Are you sure you want to continue? (yes/no): ").strip().lower()
        )
        if response not in ["yes", "y"]:
            print("Operation cancelled.")
            return 0

    deleted = query.delete(synchronize_session=False)
    db.session.commit()
    print(f"\nDeleted {deleted} articles matching the date criteria.")
    return deleted


def delete_articles_by_category(
    db: DatabaseManager, category: str, confirm: bool = True
) -> int:
    """Delete articles by category."""
    query = db.session.query(Article).filter_by(category=category)
    count = query.count()

    if count == 0:
        print(f"No articles found with category '{category}'.")
        return 0

    if confirm:
        print(
            f"\nWARNING: This will delete {count} articles with category '{category}'!"
        )
        response = (
            input("Are you sure you want to continue? (yes/no): ").strip().lower()
        )
        if response not in ["yes", "y"]:
            print("Operation cancelled.")
            return 0

    deleted = query.delete(synchronize_session=False)
    db.session.commit()
    print(f"\nDeleted {deleted} articles with category '{category}'.")
    return deleted


def delete_duplicates(db: DatabaseManager, confirm: bool = True) -> int:
    """Delete duplicate articles (same article_id or article_url)."""
    # Find duplicates by article_id
    duplicates_by_id = (
        db.session.query(
            Article.article_id,
            db.session.query(Article)
            .filter_by(article_id=Article.article_id)
            .count()
            .label("count"),
        )
        .having(
            db.session.query(Article).filter_by(article_id=Article.article_id).count()
            > 1
        )
        .all()
    )

    # Find duplicates by article_url
    duplicates_by_url = (
        db.session.query(
            Article.article_url,
            db.session.query(Article)
            .filter_by(article_url=Article.article_url)
            .count()
            .label("count"),
        )
        .having(
            db.session.query(Article).filter_by(article_url=Article.article_url).count()
            > 1
        )
        .all()
    )

    total_duplicates = 0
    articles_to_delete = []

    # Collect duplicate articles (keep the first one, delete the rest)
    for article_id, _ in duplicates_by_id:
        articles = (
            db.session.query(Article)
            .filter_by(article_id=article_id)
            .order_by(Article.scraped_at)
            .all()
        )
        if len(articles) > 1:
            articles_to_delete.extend(articles[1:])  # Keep first, delete rest
            total_duplicates += len(articles) - 1

    for article_url, _ in duplicates_by_url:
        articles = (
            db.session.query(Article)
            .filter_by(article_url=article_url)
            .order_by(Article.scraped_at)
            .all()
        )
        if len(articles) > 1:
            # Only add if not already in list (avoid double counting)
            for article in articles[1:]:
                if article not in articles_to_delete:
                    articles_to_delete.append(article)
                    total_duplicates += 1

    if total_duplicates == 0:
        print("No duplicate articles found.")
        return 0

    if confirm:
        print(f"\nWARNING: This will delete {total_duplicates} duplicate articles!")
        print("(Keeping the oldest version of each duplicate)")
        response = (
            input("Are you sure you want to continue? (yes/no): ").strip().lower()
        )
        if response not in ["yes", "y"]:
            print("Operation cancelled.")
            return 0

    deleted = 0
    for article in articles_to_delete:
        db.session.delete(article)
        deleted += 1

    db.session.commit()
    print(f"\nDeleted {deleted} duplicate articles.")
    return deleted


def reset_database(db: DatabaseManager, confirm: bool = True) -> bool:
    """Reset the entire database (drop and recreate tables)."""
    count = db.get_article_count()

    if confirm:
        print(f"\nWARNING: This will RESET the entire database!")
        print(
            f"This will delete ALL {count} articles and recreate the database schema."
        )
        response = (
            input("Are you sure you want to continue? (yes/no): ").strip().lower()
        )
        if response not in ["yes", "y"]:
            print("Operation cancelled.")
            return False

    # Close session first
    db.session.close()

    # Drop all tables
    from database import Base

    Base.metadata.drop_all(db.engine)

    # Recreate tables
    Base.metadata.create_all(db.engine)

    print("\nDatabase reset successfully. All tables have been recreated.")
    return True


def main():
    """Main function to handle command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Clean/reset the NZZ database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show database statistics
  python clean_db.py --stats
  
  # Delete all articles (with confirmation)
  python clean_db.py --delete-all
  
  # Delete all articles without confirmation
  python clean_db.py --delete-all --no-confirm
  
  # Delete articles older than 30 days
  python clean_db.py --delete-before-days 30
  
  # Delete articles in a specific category
  python clean_db.py --delete-category zuerich
  
  # Delete duplicate articles
  python clean_db.py --delete-duplicates
  
  # Reset entire database
  python clean_db.py --reset
        """,
    )

    parser.add_argument("--stats", action="store_true", help="Show database statistics")
    parser.add_argument(
        "--delete-all",
        action="store_true",
        help="Delete all articles from the database",
    )
    parser.add_argument(
        "--delete-before-days",
        type=int,
        metavar="DAYS",
        help="Delete articles scraped before N days ago",
    )
    parser.add_argument(
        "--delete-after-days",
        type=int,
        metavar="DAYS",
        help="Delete articles scraped after N days ago",
    )
    parser.add_argument(
        "--delete-category",
        type=str,
        metavar="CATEGORY",
        help="Delete articles in a specific category",
    )
    parser.add_argument(
        "--delete-duplicates",
        action="store_true",
        help="Delete duplicate articles (keep oldest)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset entire database (drop and recreate tables)",
    )
    parser.add_argument(
        "--no-confirm",
        action="store_true",
        help="Skip confirmation prompts (use with caution!)",
    )

    args = parser.parse_args()

    # If no arguments, show stats
    if len(sys.argv) == 1:
        args.stats = True

    # Initialize database
    db = DatabaseManager()

    try:
        # Show stats before operations
        if not args.stats and (
            args.delete_all
            or args.delete_before_days
            or args.delete_after_days
            or args.delete_category
            or args.delete_duplicates
            or args.reset
        ):
            print_stats(db, "Before")

        # Execute operations
        if args.stats:
            print_stats(db)

        if args.delete_all:
            delete_all_articles(db, confirm=not args.no_confirm)

        if args.delete_before_days:
            before_date = datetime.utcnow() - timedelta(days=args.delete_before_days)
            delete_articles_by_date(
                db, before_date=before_date, confirm=not args.no_confirm
            )

        if args.delete_after_days:
            after_date = datetime.utcnow() - timedelta(days=args.delete_after_days)
            delete_articles_by_date(
                db, after_date=after_date, confirm=not args.no_confirm
            )

        if args.delete_category:
            delete_articles_by_category(
                db, args.delete_category, confirm=not args.no_confirm
            )

        if args.delete_duplicates:
            delete_duplicates(db, confirm=not args.no_confirm)

        if args.reset:
            reset_database(db, confirm=not args.no_confirm)
            # Reinitialize database after reset
            db = DatabaseManager()

        # Show stats after operations
        if not args.stats and (
            args.delete_all
            or args.delete_before_days
            or args.delete_after_days
            or args.delete_category
            or args.delete_duplicates
            or args.reset
        ):
            print_stats(db, "After")

    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {str(e)}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
