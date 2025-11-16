"""14 - Clean HTML Entities from Author Names

This script cleans HTML entities (like &nbsp;, &amp;, etc.) from author names in:
- The authors table (name, alias, alt_name fields)
- The articles table (authors JSON list)

It normalizes whitespace and ensures consistent formatting.
"""
import os
import sys
import json
import re
import html
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
logger = logging.getLogger('clean_html_entities')

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


def clean_html_entities(text):
    """Clean HTML entities and normalize whitespace in text.
    
    Args:
        text: Text string that may contain HTML entities
        
    Returns:
        Cleaned text with HTML entities decoded and whitespace normalized
    """
    if not text or not isinstance(text, str):
        return text
    
    # First, normalize entities that might be missing semicolons
    # Add semicolon to common entities that are missing it (e.g., &nbsp -> &nbsp;)
    common_entities = ['nbsp', 'amp', 'lt', 'gt', 'quot', 'apos']
    cleaned = text
    for entity in common_entities:
        # Match &entity at word boundary (not followed by semicolon or alphanumeric)
        cleaned = re.sub(rf'&{entity}(?![#\w;])', f'&{entity};', cleaned)
    
    # Decode HTML entities (e.g., &nbsp; -> space, &amp; -> &, etc.)
    cleaned = html.unescape(cleaned)
    
    # Also handle numeric entities (e.g., &#160; for non-breaking space)
    # html.unescape should handle these, but we can also use regex as fallback
    cleaned = re.sub(r'&#(\d+);?', lambda m: chr(int(m.group(1))), cleaned)
    cleaned = re.sub(r'&#x([0-9a-fA-F]+);?', lambda m: chr(int(m.group(1), 16)), cleaned)
    
    # Normalize whitespace (replace all whitespace sequences with single space)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    
    # Remove leading/trailing whitespace
    cleaned = cleaned.strip()
    
    return cleaned


def has_html_entities(text):
    """Check if text contains HTML entities.
    
    Args:
        text: Text string to check
        
    Returns:
        True if text contains HTML entities, False otherwise
    """
    if not text or not isinstance(text, str):
        return False
    
    # Check for HTML entities (with or without semicolon)
    # Pattern matches: &nbsp;, &nbsp, &#160;, &#160, &amp;, &amp, etc.
    html_entity_pattern = re.compile(r'&[#\w]+;?')
    return bool(html_entity_pattern.search(text))


def clean_author_fields(author):
    """Clean HTML entities from all author name fields.
    
    Args:
        author: Author object
        
    Returns:
        Tuple of (has_changes, cleaned_fields_dict)
    """
    has_changes = False
    cleaned_fields = {}
    
    # Clean name field
    if author.name and has_html_entities(author.name):
        cleaned_name = clean_html_entities(author.name)
        if cleaned_name != author.name:
            cleaned_fields['name'] = cleaned_name
            has_changes = True
    
    # Clean alias field
    if author.alias and has_html_entities(author.alias):
        cleaned_alias = clean_html_entities(author.alias)
        if cleaned_alias != author.alias:
            cleaned_fields['alias'] = cleaned_alias
            has_changes = True
    
    # Clean alt_name field
    if author.alt_name and has_html_entities(author.alt_name):
        cleaned_alt_name = clean_html_entities(author.alt_name)
        if cleaned_alt_name != author.alt_name:
            cleaned_fields['alt_name'] = cleaned_alt_name
            has_changes = True
    
    return has_changes, cleaned_fields


def clean_articles_authors():
    """Clean HTML entities from author names in articles table."""
    logger.info("="*80)
    logger.info("14 - Clean HTML Entities from Author Names")
    logger.info("="*80)
    logger.info("Cleaning HTML entities (like &nbsp;, &amp;, etc.) from:")
    logger.info("  - Authors table (name, alias, alt_name fields)")
    logger.info("  - Articles table (authors, location, department JSON lists)")
    logger.info("="*80)
    
    processed_db = ProcessedDatabaseManager()
    
    try:
        processed_session = processed_db.Session()
        
        try:
            # Clean authors table
            logger.info("\nCleaning authors table...")
            all_authors = processed_session.query(Author).all()
            logger.info(f"Loaded {len(all_authors)} authors")
            
            authors_updated = 0
            authors_name_updated = 0
            authors_alias_updated = 0
            authors_alt_name_updated = 0
            
            for author in all_authors:
                has_changes, cleaned_fields = clean_author_fields(author)
                
                if has_changes:
                    # Update fields
                    if 'name' in cleaned_fields:
                        author.name = cleaned_fields['name']
                        authors_name_updated += 1
                    if 'alias' in cleaned_fields:
                        author.alias = cleaned_fields['alias']
                        authors_alias_updated += 1
                    if 'alt_name' in cleaned_fields:
                        author.alt_name = cleaned_fields['alt_name']
                        authors_alt_name_updated += 1
                    
                    authors_updated += 1
                    
                    if authors_updated % 100 == 0:
                        logger.info(f"Cleaned {authors_updated} authors...")
            
            logger.info(f"Authors table: Updated {authors_updated} authors")
            logger.info(f"  - Name field: {authors_name_updated}")
            logger.info(f"  - Alias field: {authors_alias_updated}")
            logger.info(f"  - Alt name field: {authors_alt_name_updated}")
            
            # Clean articles table
            logger.info("\nCleaning articles table...")
            all_articles = processed_session.query(Article).filter(
                or_(
                    Article.authors.isnot(None),
                    Article.location.isnot(None),
                    Article.department.isnot(None)
                )
            ).all()
            logger.info(f"Loaded {len(all_articles)} articles with authors/locations/departments")
            
            articles_updated = 0
            author_names_cleaned = 0
            location_names_cleaned = 0
            department_names_cleaned = 0
            
            for article in all_articles:
                has_article_changes = False
                
                # Clean authors
                if article.authors:
                    try:
                        author_list = json.loads(article.authors) if isinstance(article.authors, str) else article.authors
                        if isinstance(author_list, list):
                            # Clean each author name in the list
                            updated = False
                            cleaned_list = []
                            
                            for author_name in author_list:
                                if not isinstance(author_name, str):
                                    cleaned_list.append(author_name)
                                    continue
                                
                                # Check if it has HTML entities
                                if has_html_entities(author_name):
                                    cleaned_name = clean_html_entities(author_name)
                                    cleaned_list.append(cleaned_name)
                                    if cleaned_name != author_name:
                                        updated = True
                                        author_names_cleaned += 1
                                else:
                                    cleaned_list.append(author_name)
                            
                            if updated:
                                # Update article with cleaned author list
                                article.authors = json.dumps(cleaned_list, ensure_ascii=False)
                                has_article_changes = True
                    
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.debug(f"Error processing authors for article {article.article_id}: {str(e)}")
                
                # Clean locations
                if article.location:
                    try:
                        location_list = json.loads(article.location) if isinstance(article.location, str) else article.location
                        if isinstance(location_list, list):
                            # Clean each location in the list
                            updated = False
                            cleaned_list = []
                            
                            for location in location_list:
                                if not isinstance(location, str):
                                    cleaned_list.append(location)
                                    continue
                                
                                # Check if it has HTML entities
                                if has_html_entities(location):
                                    cleaned_location = clean_html_entities(location)
                                    cleaned_list.append(cleaned_location)
                                    if cleaned_location != location:
                                        updated = True
                                        location_names_cleaned += 1
                                else:
                                    cleaned_list.append(location)
                            
                            if updated:
                                # Update article with cleaned location list
                                article.location = json.dumps(cleaned_list, ensure_ascii=False)
                                has_article_changes = True
                    
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.debug(f"Error processing locations for article {article.article_id}: {str(e)}")
                
                # Clean departments
                if article.department:
                    try:
                        department_list = json.loads(article.department) if isinstance(article.department, str) else article.department
                        if isinstance(department_list, list):
                            # Clean each department in the list
                            updated = False
                            cleaned_list = []
                            
                            for department in department_list:
                                if not isinstance(department, str):
                                    cleaned_list.append(department)
                                    continue
                                
                                # Check if it has HTML entities
                                if has_html_entities(department):
                                    cleaned_department = clean_html_entities(department)
                                    cleaned_list.append(cleaned_department)
                                    if cleaned_department != department:
                                        updated = True
                                        department_names_cleaned += 1
                                else:
                                    cleaned_list.append(department)
                            
                            if updated:
                                # Update article with cleaned department list
                                article.department = json.dumps(cleaned_list, ensure_ascii=False)
                                has_article_changes = True
                    
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.debug(f"Error processing departments for article {article.article_id}: {str(e)}")
                
                if has_article_changes:
                    articles_updated += 1
                
                # Commit every 500 articles
                if articles_updated > 0 and articles_updated % 500 == 0:
                    try:
                        processed_session.commit()
                        logger.info(f"Processed {articles_updated} articles... (authors: {author_names_cleaned}, locations: {location_names_cleaned}, depts: {department_names_cleaned})")
                    except Exception as commit_error:
                        processed_session.rollback()
                        logger.warning(f"Commit error (will retry): {str(commit_error)}")
            
            logger.info(f"Articles table: Updated {articles_updated} articles")
            logger.info(f"  - Author names cleaned: {author_names_cleaned}")
            logger.info(f"  - Location names cleaned: {location_names_cleaned}")
            logger.info(f"  - Department names cleaned: {department_names_cleaned}")
            
            # Final commit
            try:
                processed_session.commit()
                logger.info("\nAll changes committed successfully!")
            except Exception as commit_error:
                processed_session.rollback()
                logger.error(f"Final commit error: {str(commit_error)}")
                logger.error("Some changes may not have been saved. Please close any database viewers and rerun.")
                raise
            
            # Summary
            logger.info("\n" + "="*80)
            logger.info("Processing complete!")
            logger.info("="*80)
            logger.info(f"Authors updated: {authors_updated}")
            logger.info(f"  - Name fields: {authors_name_updated}")
            logger.info(f"  - Alias fields: {authors_alias_updated}")
            logger.info(f"  - Alt name fields: {authors_alt_name_updated}")
            logger.info(f"Articles updated: {articles_updated}")
            logger.info(f"  - Author names cleaned: {author_names_cleaned}")
            logger.info(f"  - Location names cleaned: {location_names_cleaned}")
            logger.info(f"  - Department names cleaned: {department_names_cleaned}")
            logger.info("="*80)
            
        finally:
            processed_session.close()
    
    finally:
        processed_db.close()


if __name__ == '__main__':
    clean_articles_authors()

