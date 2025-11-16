"""12 - Match Article Authors to Authors Table

This script goes through all authors in the articles table and tries to match them
to existing authors in the authors table (checking name, alias, and alt_name).
If no match is found, creates a new author entry with:
- author_id: "non-imp-{number}" (unique number)
- name: the author name from article
- title: None
- alt_name: None
- alias: None
- department: None
- location: None
- tags: None
- bio: None
- has_info: 0
"""
import os
import sys
import json
import logging
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
logger = logging.getLogger('match_articles_authors')

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

    def __repr__(self):
        return f"<Article(article_id='{self.article_id}', title='{self.title[:50]}...')>"


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

    def __repr__(self):
        return f"<Author(author_id='{self.author_id}', name='{self.name}')>"


class ProcessedDatabaseManager:
    """Manages database connection for processed tables."""
    
    def __init__(self, db_path=None):
        """Initialize database connection.
        
        Args:
            db_path: Path to database file. If None, uses default path in NZZ folder.
        """
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
        
        # Create tables if they don't exist
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


def normalize_name(name):
    """Normalize author name for comparison.
    
    Args:
        name: Author name string
        
    Returns:
        Normalized name (lowercase, stripped)
    """
    if not name or not isinstance(name, str):
        return ""
    return name.strip().lower()


def find_matching_author(session, author_name, author_lookup=None):
    """Find an existing author that matches the given name.
    
    Checks against name, alias, and alt_name fields (case-insensitive).
    
    Args:
        session: Database session
        author_name: Author name to match
        author_lookup: Optional pre-built lookup dictionary (normalized_name -> Author)
        
    Returns:
        Author object if match found, None otherwise
    """
    if not author_name or not isinstance(author_name, str):
        return None
    
    normalized = normalize_name(author_name)
    if not normalized:
        return None
    
    # First check lookup if provided
    if author_lookup and normalized in author_lookup:
        return author_lookup[normalized]
    
    # Fallback: query database and check normalized names
    # SQLite LIKE is case-insensitive for ASCII, but we'll do Python normalization
    all_authors = session.query(Author).all()
    for author in all_authors:
        if (normalize_name(author.name) == normalized or
            normalize_name(author.alias) == normalized or
            normalize_name(author.alt_name) == normalized):
            return author
    
    return None


def get_next_non_imp_number(session):
    """Get the next available number for non-imp author_id.
    
    Args:
        session: Database session
        
    Returns:
        Next available number (e.g., if highest is "non-imp-123", returns 124)
    """
    # Find all existing non-imp author_ids
    existing_authors = session.query(Author).filter(
        Author.author_id.like('non-imp-%')
    ).all()
    
    max_num = 0
    for author in existing_authors:
        if author.author_id and author.author_id.startswith('non-imp-'):
            try:
                num_str = author.author_id.replace('non-imp-', '')
                num = int(num_str)
                if num > max_num:
                    max_num = num
            except ValueError:
                continue
    
    return max_num + 1


def match_articles_authors():
    """Match article authors to authors table and create missing entries."""
    logger.info("="*80)
    logger.info("12 - Match Article Authors to Authors Table")
    logger.info("="*80)
    logger.info("Processing authors from articles table:")
    logger.info("  - Matching against existing authors (name, alias, alt_name)")
    logger.info("  - Creating new authors for unmatched names")
    logger.info("="*80)
    
    processed_db = ProcessedDatabaseManager()
    
    try:
        processed_session = processed_db.Session()
        
        try:
            # Load all existing authors into memory for faster lookup
            logger.info("Loading existing authors...")
            all_authors = processed_session.query(Author).all()
            author_lookup = {}
            
            for author in all_authors:
                # Index by normalized name, alias, and alt_name
                if author.name:
                    norm_name = normalize_name(author.name)
                    if norm_name:
                        author_lookup[norm_name] = author
                if author.alias:
                    norm_alias = normalize_name(author.alias)
                    if norm_alias:
                        author_lookup[norm_alias] = author
                if author.alt_name:
                    norm_alt = normalize_name(author.alt_name)
                    if norm_alt:
                        author_lookup[norm_alt] = author
            
            logger.info(f"Loaded {len(all_authors)} existing authors into lookup table")
            
            # Get all articles with authors
            logger.info("Loading articles with authors...")
            all_articles = processed_session.query(Article).filter(
                Article.authors.isnot(None)
            ).all()
            
            logger.info(f"Found {len(all_articles)} articles with authors")
            
            # Track statistics
            total_author_names = 0
            matched_count = 0
            created_count = 0
            skipped_count = 0  # Empty or invalid names
            processed_articles = 0
            next_number = get_next_non_imp_number(processed_session)
            
            # Process each article
            for article in all_articles:
                try:
                    if not article.authors:
                        continue
                    
                    # Parse authors JSON
                    try:
                        author_list = json.loads(article.authors) if isinstance(article.authors, str) else article.authors
                        if not isinstance(author_list, list):
                            continue
                    except (json.JSONDecodeError, TypeError):
                        logger.debug(f"Could not parse authors for article {article.article_id}")
                        continue
                    
                    # Process each author name
                    for author_name in author_list:
                        if not isinstance(author_name, str) or not author_name.strip():
                            skipped_count += 1
                            continue
                        
                        total_author_names += 1
                        normalized = normalize_name(author_name)
                        
                        if not normalized:
                            skipped_count += 1
                            continue
                        
                        # Check if author exists in lookup
                        if normalized in author_lookup:
                            matched_count += 1
                            continue
                        
                        # Try database query as fallback (in case lookup missed something)
                        existing_author = find_matching_author(processed_session, author_name, author_lookup)
                        if existing_author:
                            matched_count += 1
                            # Add to lookup for future checks
                            author_lookup[normalized] = existing_author
                            continue
                        
                        # No match found - create new author
                        new_author_id = f"non-imp-{next_number}"
                        next_number += 1
                        
                        new_author = Author(
                            author_id=new_author_id,
                            name=author_name.strip(),
                            title=None,
                            alt_name=None,
                            alias=None,
                            department=None,
                            location=None,
                            tags=None,
                            bio=None,
                            has_info=0
                        )
                        
                        processed_session.add(new_author)
                        created_count += 1
                        
                        # Add to lookup to avoid duplicates
                        author_lookup[normalized] = new_author
                        
                        if created_count % 100 == 0:
                            logger.info(f"Created {created_count} new authors... (matched: {matched_count}, processed: {total_author_names})")
                    
                    processed_articles += 1
                    
                    # Commit every 500 articles
                    if processed_articles % 500 == 0:
                        try:
                            processed_session.commit()
                            logger.info(f"Processed {processed_articles} articles... (created: {created_count}, matched: {matched_count})")
                        except Exception as commit_error:
                            processed_session.rollback()
                            logger.warning(f"Commit error (will retry): {str(commit_error)}")
                
                except Exception as e:
                    logger.error(f"Error processing article {article.article_id}: {str(e)}")
                    try:
                        processed_session.rollback()
                    except Exception:
                        pass
                    continue
            
            # Final commit
            try:
                processed_session.commit()
            except Exception as commit_error:
                processed_session.rollback()
                logger.error(f"Final commit error: {str(commit_error)}")
                logger.error("Some changes may not have been saved. Please close any database viewers and rerun.")
                raise
            
            logger.info("="*80)
            logger.info("Processing complete!")
            logger.info("="*80)
            logger.info(f"Articles processed: {processed_articles}")
            logger.info(f"Total author names processed: {total_author_names}")
            logger.info(f"Authors matched to existing: {matched_count}")
            logger.info(f"New authors created: {created_count}")
            logger.info(f"Names skipped (empty/invalid): {skipped_count}")
            logger.info("="*80)
            
        finally:
            processed_session.close()
    
    finally:
        processed_db.close()


if __name__ == '__main__':
    match_articles_authors()

