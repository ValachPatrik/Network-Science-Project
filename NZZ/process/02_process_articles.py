"""02 - Process Articles

This script processes raw article data from articles_raw table and creates
processed articles in the articles table with the following columns:
- id
- article_id
- title
- content
- description
- tags
- category
- authors (empty - needs processing)
- department (empty - needs processing)
- location (empty - needs processing)
- related_articles (empty - needs processing)
- article_date
- article_date_updated

Only columns that don't require extra processing are populated.
"""
import os
import sys
import logging
from sqlalchemy import create_engine, Column, String, Text, Integer, DateTime, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import NullPool

# Add parent directory to path to import database_v3
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

from database_v3 import DatabaseManagerV3, ArticleRaw

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('process_articles')

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
    authors = Column(Text, nullable=True)  # Empty - needs processing
    department = Column(String(200), nullable=True)  # Empty - needs processing
    location = Column(String(200), nullable=True)  # Empty - needs processing
    related_articles = Column(Text, nullable=True)  # Empty - needs processing
    article_date = Column(DateTime, nullable=True)
    article_date_updated = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<Article(article_id='{self.article_id}', title='{self.title[:50]}...')>"


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
        
        # Check if articles table exists and has correct schema
        self._ensure_articles_table_schema()
        
        # Create processed tables
        Base.metadata.create_all(self.engine)
        
        session_factory = sessionmaker(bind=self.engine)
        self.Session = scoped_session(session_factory)
        self.db_path = db_path
    
    def _ensure_articles_table_schema(self):
        """Ensure articles table has the correct schema.
        
        If the old articles table exists with different columns, we drop and recreate it
        to match the new schema.
        """
        try:
            with self.engine.connect() as conn:
                # Check if table exists
                result = conn.execute(text("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='articles'
                """))
                table_exists = result.fetchone() is not None
                
                if table_exists:
                    # Check if table has correct schema
                    result = conn.execute(text("PRAGMA table_info(articles)"))
                    columns = [row[1] for row in result.fetchall()]
                    
                    required_columns = {
                        'id', 'article_id', 'title', 'content', 'description', 'tags', 
                        'category', 'authors', 'department', 'location', 'related_articles',
                        'article_date', 'article_date_updated'
                    }
                    existing_columns = set(columns)
                    
                    # If schema doesn't match, drop and recreate
                    if not required_columns.issubset(existing_columns):
                        logger.info("Articles table has old schema. Dropping and recreating with new schema...")
                        conn.execute(text("DROP TABLE IF EXISTS articles"))
                        conn.commit()
                        logger.info("Old articles table dropped. Will be recreated with correct schema.")
                    else:
                        logger.info("Articles table schema is correct")
        except Exception as e:
            logger.warning(f"Could not check/update articles table schema: {str(e)}")
            # Continue anyway - Base.metadata.create_all will handle it
    
    def close(self):
        """Close database connections."""
        try:
            if hasattr(self, 'Session') and self.Session:
                self.Session.remove()
            if hasattr(self, 'engine') and self.engine:
                self.engine.dispose()
        except Exception as e:
            logger.warning(f"Error closing database connections: {str(e)}")


def process_articles():
    """Process articles from articles_raw to articles table."""
    logger.info("="*80)
    logger.info("02 - Processing Articles")
    logger.info("Processing articles from articles_raw to articles table")
    logger.info("="*80)
    
    # Initialize database managers
    raw_db = DatabaseManagerV3()
    processed_db = ProcessedDatabaseManager()
    
    try:
        # Get all articles from articles_raw
        raw_session = raw_db.Session()
        processed_session = processed_db.Session()
        
        try:
            all_raw_articles = raw_session.query(ArticleRaw).all()
            logger.info(f"Found {len(all_raw_articles)} articles in articles_raw table")
            
            processed_count = 0
            updated_count = 0
            error_count = 0
            
            for raw_article in all_raw_articles:
                try:
                    # Check if article already exists in processed table
                    existing_article = processed_session.query(Article).filter_by(
                        article_id=raw_article.article_id
                    ).first()
                    
                    if existing_article:
                        # Update existing article (only non-processing columns)
                        existing_article.title = raw_article.title
                        existing_article.content = raw_article.content
                        existing_article.description = raw_article.description
                        existing_article.tags = raw_article.tags
                        existing_article.category = raw_article.category
                        existing_article.article_date = raw_article.article_date
                        existing_article.article_date_updated = raw_article.article_updated
                        # Keep authors, department, location, related_articles as None (need processing)
                        updated_count += 1
                    else:
                        # Create new article
                        new_article = Article(
                            article_id=raw_article.article_id,
                            title=raw_article.title,
                            content=raw_article.content,
                            description=raw_article.description,
                            tags=raw_article.tags,
                            category=raw_article.category,
                            authors=None,  # Empty - needs processing
                            department=None,  # Empty - needs processing
                            location=None,  # Empty - needs processing
                            related_articles=None,  # Empty - needs processing
                            article_date=raw_article.article_date,
                            article_date_updated=raw_article.article_updated
                        )
                        processed_session.add(new_article)
                        processed_count += 1
                    
                    # Commit every 100 records
                    if (processed_count + updated_count) % 100 == 0:
                        processed_session.commit()
                        logger.info(f"Processed {processed_count + updated_count} articles...")
                
                except Exception as e:
                    error_count += 1
                    logger.error(f"Error processing article {raw_article.article_id}: {str(e)}")
                    processed_session.rollback()
                    continue
            
            # Final commit
            processed_session.commit()
            
            logger.info("="*80)
            logger.info("Processing complete!")
            logger.info("="*80)
            logger.info(f"New articles created: {processed_count}")
            logger.info(f"Existing articles updated: {updated_count}")
            logger.info(f"Errors: {error_count}")
            logger.info(f"Total processed: {processed_count + updated_count}")
            logger.info("="*80)
            logger.info("Note: authors, department, location, and related_articles columns")
            logger.info("      are left empty and will be populated by later processing steps.")
            logger.info("="*80)
            
        finally:
            raw_session.close()
            processed_session.close()
    
    finally:
        raw_db.close()
        processed_db.close()


if __name__ == '__main__':
    process_articles()



