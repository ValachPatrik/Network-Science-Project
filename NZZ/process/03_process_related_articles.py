"""03 - Process Related Articles

This script processes related articles from articles_raw table and populates
the related_articles column in the articles table with a JSON list of article IDs.

The related_articles column in articles_raw contains JSON like:
[{"id": "article_id_1", "url": "..."}, {"id": "article_id_2", "url": "..."}]

This script extracts just the IDs and stores them in articles.related_articles as:
["article_id_1", "article_id_2", ...]
"""
import os
import sys
import json
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
logger = logging.getLogger('process_related_articles')

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
    authors = Column(Text, nullable=True)
    department = Column(String(200), nullable=True)
    location = Column(String(200), nullable=True)
    related_articles = Column(Text, nullable=True)  # JSON string of related article IDs
    article_date = Column(DateTime, nullable=True)
    article_date_updated = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<Article(article_id='{self.article_id}', title='{self.title[:50]}...')>"


class ProcessedDatabaseManager:
    """Manages database connection for processed tables."""
    
    def __init__(self, db_path=None):
        if db_path is None:
            db_path = os.path.join(PARENT_DIR, 'nzz_scraped_articles.db')
        
        db_path = os.path.normpath(db_path)
        logger.info(f"Database path: {db_path}")
        
        self.engine = create_engine(
            f'sqlite:///{db_path}',
            echo=False,
            poolclass=NullPool,
            connect_args={'check_same_thread': False}
        )
        self.Session = scoped_session(sessionmaker(bind=self.engine))
        self.db_path = db_path
    
    def close(self):
        """Close database connections."""
        try:
            if hasattr(self, 'Session') and self.Session:
                self.Session.remove()
            if hasattr(self, 'engine') and self.engine:
                self.engine.dispose()
        except Exception as e:
            logger.warning(f"Error closing database connections: {str(e)}")


def process_related_articles():
    """Process related articles from articles_raw to articles table."""
    logger.info("="*80)
    logger.info("03 - Process Related Articles")
    logger.info("="*80)
    logger.info("Processing related articles from articles_raw to articles table")
    logger.info("="*80)
    
    # Initialize database managers
    raw_db = DatabaseManagerV3()
    processed_db = ProcessedDatabaseManager()
    
    try:
        # Create tables if they don't exist
        Base.metadata.create_all(processed_db.engine)
        
        raw_session = raw_db.Session()
        processed_session = processed_db.Session()
        
        try:
            # Get all articles from articles_raw that have related_articles
            logger.info("Loading articles with related articles from articles_raw...")
            all_raw_articles = raw_session.query(ArticleRaw).filter(
                ArticleRaw.related_articles.isnot(None),
                ArticleRaw.related_articles != ''
            ).all()
            
            total_raw_articles = len(all_raw_articles)
            logger.info(f"Found {total_raw_articles} articles with related articles in articles_raw")
            
            if total_raw_articles == 0:
                logger.info("No articles with related articles found. Exiting.")
                return
            
            updated_count = 0
            skipped_count = 0
            error_count = 0
            
            for raw_article in all_raw_articles:
                try:
                    # Find corresponding article in processed table
                    processed_article = processed_session.query(Article).filter_by(
                        article_id=raw_article.article_id
                    ).first()
                    
                    if not processed_article:
                        skipped_count += 1
                        logger.debug(f"Article {raw_article.article_id} not found in articles table, skipping")
                        continue
                    
                    # Parse related_articles JSON from articles_raw
                    try:
                        related_data = json.loads(raw_article.related_articles)
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.debug(f"Error parsing related_articles JSON for article {raw_article.article_id}: {str(e)}")
                        error_count += 1
                        continue
                    
                    # Extract just the IDs from the related articles
                    # related_data is a list of dicts: [{"id": "...", "url": "..."}, ...]
                    related_ids = []
                    if isinstance(related_data, list):
                        for item in related_data:
                            if isinstance(item, dict):
                                related_id = item.get('id')
                                if related_id:
                                    related_ids.append(related_id)
                            elif isinstance(item, str):
                                # Backward compatibility: if it's just a string ID
                                related_ids.append(item)
                    
                    # Convert to JSON string (list of IDs)
                    related_articles_json = json.dumps(related_ids) if related_ids else None
                    
                    # Update the processed article
                    processed_article.related_articles = related_articles_json
                    updated_count += 1
                    
                    # Commit every 100 records
                    if updated_count % 100 == 0:
                        processed_session.commit()
                        logger.info(f"Processed {updated_count} articles...")
                
                except Exception as e:
                    error_count += 1
                    logger.error(f"Error processing article {raw_article.article_id}: {str(e)}")
                    continue
            
            # Final commit
            processed_session.commit()
            
            logger.info("="*80)
            logger.info("Processing complete!")
            logger.info("="*80)
            logger.info(f"Articles updated: {updated_count}")
            logger.info(f"Articles skipped (not in processed table): {skipped_count}")
            logger.info(f"Errors: {error_count}")
            logger.info(f"Total articles with related articles in raw: {total_raw_articles}")
            logger.info("="*80)
            
        finally:
            raw_session.close()
            processed_session.close()
    
    finally:
        raw_db.close()
        processed_db.close()


if __name__ == '__main__':
    process_related_articles()



