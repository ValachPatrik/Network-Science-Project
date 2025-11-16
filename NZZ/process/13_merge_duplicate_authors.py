"""13 - Merge Duplicate Authors

This script finds and merges duplicate author entries that represent the same person
but have different entries (e.g., "Peter A. Fischer", "Peter A.&nbsp;Fischer", "Peter A.&nbsp;").

It normalizes names in both:
- The authors table (merges duplicates into one canonical entry)
- The articles table (updates author references to point to the canonical author)
"""
import os
import sys
import json
import re
import html
import logging
from collections import defaultdict
from sqlalchemy import create_engine, Column, String, Text, Integer, DateTime, or_
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import NullPool

# Add parent directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('merge_duplicate_authors')

Base = declarative_base()


class Article(Base):
    """Processed article data."""
    __tablename__ = 'articles'

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(String(255), unique=True, nullable=False, index=True)
    title = Column(String(500), nullable=True)
    content = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    tags = Column(String(1000), nullable=True)
    category = Column(String(200), nullable=True)
    authors = Column(Text, nullable=True)  # JSON list of author names
    department = Column(String(200), nullable=True)
    location = Column(String(200), nullable=True)
    related_articles = Column(Text, nullable=True)
    article_date = Column(DateTime, nullable=True)
    article_date_updated = Column(DateTime, nullable=True)


class Author(Base):
    """Processed author data."""
    __tablename__ = 'authors'

    id = Column(Integer, primary_key=True, autoincrement=True)
    author_id = Column(String(255), unique=True, nullable=True, index=True)
    name = Column(String(200), nullable=False)
    title = Column(String(200), nullable=True)
    alt_name = Column(String(100), nullable=True)
    alias = Column(String(200), nullable=True)
    department = Column(String(200), nullable=True)
    location = Column(String(200), nullable=True)
    tags = Column(String(1000), nullable=True)
    bio = Column(Text, nullable=True)
    has_info = Column(Integer, default=0, nullable=False)


class ProcessedDatabaseManager:
    """Manages database connection for processed tables."""
    
    def __init__(self, db_path=None):
        """Initialize database connection."""
        if db_path is None:
            db_path = os.path.join(PARENT_DIR, 'nzz_scraped_articles.db')
        else:
            if not os.path.isabs(db_path):
                db_path = os.path.join(PARENT_DIR, db_path)
        
        db_path = os.path.normpath(db_path)
        
        logger.info(f"Database path: {db_path}")
        
        self.engine = create_engine(
            f'sqlite:///{db_path}',
            echo=False,
            poolclass=NullPool,
            connect_args={'check_same_thread': False}
        )
        
        Base.metadata.create_all(self.engine)
        
        session_factory = sessionmaker(bind=self.engine)
        self.Session = scoped_session(session_factory)
        self.db_path = db_path
    
    def close(self):
        """Close database connections."""
        try:
            self.Session.remove()
            if hasattr(self, 'engine'):
                self.engine.dispose()
        except Exception as e:
            logger.warning(f"Error closing database connections: {str(e)}")


def clean_name(name):
    """Clean author name by removing HTML entities and normalizing whitespace.
    
    Args:
        name: Author name string
        
    Returns:
        Cleaned name
    """
    if not name or not isinstance(name, str):
        return ""
    
    # Decode HTML entities (e.g., &nbsp; -> space)
    cleaned = html.unescape(name)
    
    # Normalize whitespace (replace all whitespace with single space)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    
    # Strip leading/trailing whitespace
    cleaned = cleaned.strip()
    
    return cleaned


def normalize_name_for_matching(name):
    """Normalize author name for duplicate detection.
    
    Args:
        name: Author name string
        
    Returns:
        Normalized name for matching (lowercase, cleaned, no punctuation variations)
    """
    if not name:
        return ""
    
    # Clean first
    cleaned = clean_name(name)
    
    # Convert to lowercase
    normalized = cleaned.lower()
    
    # Remove common punctuation variations that don't affect identity
    # Keep periods in initials (e.g., "Peter A. Fischer")
    normalized = re.sub(r'[^\w\s\.]', '', normalized)
    
    # Normalize whitespace
    normalized = re.sub(r'\s+', ' ', normalized)
    
    return normalized.strip()


def find_duplicate_groups(session):
    """Find groups of authors that are likely duplicates.
    
    Args:
        session: Database session
        
    Returns:
        Dictionary mapping normalized name to list of Author objects
    """
    logger.info("Loading all authors...")
    all_authors = session.query(Author).all()
    logger.info(f"Loaded {len(all_authors)} authors")
    
    # Group by normalized name
    groups = defaultdict(list)
    
    for author in all_authors:
        if not author.name:
            continue
        
        normalized = normalize_name_for_matching(author.name)
        if normalized:
            groups[normalized].append(author)
    
    # Filter to only groups with 2+ authors (potential duplicates)
    duplicate_groups = {k: v for k, v in groups.items() if len(v) > 1}
    
    logger.info(f"Found {len(duplicate_groups)} potential duplicate groups")
    
    return duplicate_groups


def choose_canonical_author(authors):
    """Choose the best author to keep as canonical.
    
    Priority:
    1. Author with has_info=1 (from impressum)
    2. Author with most complete information (non-NULL fields)
    3. Author with shortest author_id (likely original)
    4. First author
    
    Args:
        authors: List of Author objects
        
    Returns:
        Author object to keep as canonical
    """
    if not authors:
        return None
    
    # Sort by priority
    def priority(author):
        score = 0
        # Prefer authors with has_info=1
        if author.has_info == 1:
            score += 1000
        # Prefer authors with more complete info
        if author.title:
            score += 100
        if author.bio:
            score += 50
        if author.department:
            score += 10
        # Prefer non-imp authors (they have numeric IDs)
        if author.author_id and not author.author_id.startswith('non-imp-'):
            score += 5
        return score
    
    sorted_authors = sorted(authors, key=priority, reverse=True)
    return sorted_authors[0]


def merge_author_group(session, authors, canonical_author):
    """Merge a group of duplicate authors into the canonical one.
    
    Args:
        session: Database session
        authors: List of Author objects (duplicates)
        canonical_author: Author object to keep
        
    Returns:
        Tuple of (articles_updated_count, authors_deleted_count)
    """
    articles_updated = 0
    authors_deleted = 0
    
    # Get canonical name (cleaned)
    canonical_name = clean_name(canonical_author.name)
    
    # Process each duplicate author
    for author in authors:
        if author.id == canonical_author.id:
            continue  # Skip canonical author itself
        
        duplicate_name = clean_name(author.name)
        
        # Find all articles that reference this duplicate author
        articles = session.query(Article).filter(
            Article.authors.isnot(None)
        ).all()
        
        for article in articles:
            if not article.authors:
                continue
            
            try:
                author_list = json.loads(article.authors) if isinstance(article.authors, str) else article.authors
                if not isinstance(author_list, list):
                    continue
                
                # Check if this article references the duplicate author
                updated = False
                new_author_list = []
                
                for author_name in author_list:
                    if not isinstance(author_name, str):
                        new_author_list.append(author_name)
                        continue
                    
                    # Check if this name matches the duplicate (normalized comparison)
                    author_normalized = normalize_name_for_matching(author_name)
                    duplicate_normalized = normalize_name_for_matching(duplicate_name)
                    
                    if author_normalized == duplicate_normalized and author_normalized:
                        # Replace with canonical name
                        new_author_list.append(canonical_name)
                        updated = True
                    else:
                        new_author_list.append(author_name)
                
                if updated:
                    # Update article with canonical name
                    article.authors = json.dumps(new_author_list, ensure_ascii=False)
                    articles_updated += 1
            
            except (json.JSONDecodeError, TypeError):
                continue
        
        # Delete duplicate author
        session.delete(author)
        authors_deleted += 1
    
    return articles_updated, authors_deleted


def merge_duplicate_authors(interactive=True, auto_merge=False, dry_run=False):
    """Find and merge duplicate authors.
    
    Args:
        interactive: If True, show each group and ask for confirmation
        auto_merge: If True, automatically merge without asking (only if interactive=False)
        dry_run: If True, only show what would be merged without making changes
    """
    logger.info("="*80)
    logger.info("13 - Merge Duplicate Authors")
    logger.info("="*80)
    logger.info("Finding duplicate author entries and merging them...")
    logger.info("="*80)
    
    processed_db = ProcessedDatabaseManager()
    
    try:
        processed_session = processed_db.Session()
        
        try:
            # Find duplicate groups
            duplicate_groups = find_duplicate_groups(processed_session)
            
            if not duplicate_groups:
                logger.info("No duplicate groups found!")
                return
            
            logger.info(f"\nFound {len(duplicate_groups)} potential duplicate groups")
            logger.info("="*80)
            
            total_articles_updated = 0
            total_authors_deleted = 0
            merged_groups = 0
            skipped_groups = 0
            
            # Process each group
            for i, (normalized_name, authors) in enumerate(duplicate_groups.items(), 1):
                if len(authors) < 2:
                    continue
                
                # Choose canonical author
                canonical = choose_canonical_author(authors)
                
                if not canonical:
                    continue
                
                # Show group info
                print(f"\n{'='*80}")
                print(f"Group {i}/{len(duplicate_groups)}: {normalized_name}")
                print(f"{'='*80}")
                print(f"\nFound {len(authors)} duplicate entries:")
                
                for j, author in enumerate(authors, 1):
                    is_canonical = (author.id == canonical.id)
                    marker = " [CANONICAL - will keep]" if is_canonical else " [will delete]"
                    print(f"\n  {j}. ID: {author.id}, author_id: {author.author_id}")
                    print(f"     Name: '{author.name}'")
                    print(f"     Title: {author.title or '(NULL)'}")
                    print(f"     Alias: {author.alias or '(NULL)'}")
                    print(f"     Alt Name: {author.alt_name or '(NULL)'}")
                    print(f"     Has Info: {author.has_info}")
                    print(f"     Department: {author.department or '(NULL)'}{marker}")
                
                print(f"\n  -> Will keep: ID {canonical.id} ('{canonical.name}')")
                print(f"  -> Will delete: {len(authors) - 1} duplicate(s)")
                
                # Ask for confirmation if interactive
                if dry_run:
                    logger.info("[DRY RUN] Would merge this group (no changes made)")
                    skipped_groups += 1
                    continue
                elif interactive:
                    try:
                        response = input("\nMerge this group? (y/n/s=skip all remaining/q=quit): ").strip().lower()
                        if response == 'q':
                            logger.info("User quit. Stopping...")
                            break
                        elif response == 's':
                            logger.info("Skipping remaining groups...")
                            break
                        elif response != 'y':
                            skipped_groups += 1
                            logger.info("Skipped.")
                            continue
                    except (EOFError, KeyboardInterrupt):
                        logger.info("\nInterrupted. Stopping...")
                        break
                elif not auto_merge:
                    logger.info("Auto-merge disabled. Skipping...")
                    continue
                
                # Merge the group
                try:
                    articles_updated, authors_deleted = merge_author_group(
                        processed_session, authors, canonical
                    )
                    
                    total_articles_updated += articles_updated
                    total_authors_deleted += authors_deleted
                    merged_groups += 1
                    
                    logger.info(f"✓ Merged group {i}: Updated {articles_updated} articles, deleted {authors_deleted} authors")
                    
                    # Commit after each merge
                    try:
                        processed_session.commit()
                    except Exception as commit_error:
                        processed_session.rollback()
                        logger.error(f"Commit error: {str(commit_error)}")
                        raise
                
                except Exception as e:
                    logger.error(f"Error merging group {i}: {str(e)}")
                    processed_session.rollback()
                    continue
            
            # Final summary
            logger.info("\n" + "="*80)
            logger.info("Processing complete!")
            logger.info("="*80)
            logger.info(f"Groups processed: {len(duplicate_groups)}")
            logger.info(f"Groups merged: {merged_groups}")
            logger.info(f"Groups skipped: {skipped_groups}")
            logger.info(f"Total articles updated: {total_articles_updated}")
            logger.info(f"Total authors deleted: {total_authors_deleted}")
            logger.info("="*80)
            
        finally:
            processed_session.close()
    
    finally:
        processed_db.close()


if __name__ == '__main__':
    import sys
    
    # Check for command line arguments
    interactive = True
    auto_merge = False
    
    if len(sys.argv) > 1:
        if '--auto' in sys.argv or '-a' in sys.argv:
            interactive = False
            auto_merge = True
            dry_run = False
        elif '--dry-run' in sys.argv or '-d' in sys.argv:
            interactive = False
            auto_merge = False
            dry_run = True
        else:
            dry_run = False
    else:
        dry_run = False
    
    merge_duplicate_authors(interactive=interactive, auto_merge=auto_merge, dry_run=dry_run)

