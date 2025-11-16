"""01 - Process Impressum Authors

This script processes raw author data from authors_raw table (scraped from impressum)
and creates processed authors in the authors table with the following columns:
- id
- author_id
- name
- title
- alt_name
- alias
- department
- location (empty - needs processing)
- tags (empty - needs processing)
- bio
- has_info
"""
import os
import sys
import logging
from sqlalchemy import create_engine, Column, String, Text, Integer, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import NullPool

# Add parent directory to path to import database_v3
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

from database_v3 import DatabaseManagerV3, AuthorRaw

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('process_authors')

Base = declarative_base()


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
    location = Column(String(200), nullable=True)  # Empty - needs processing
    tags = Column(String(1000), nullable=True)  # Empty - needs processing
    bio = Column(Text, nullable=True)
    has_info = Column(Integer, default=0, nullable=False)

    def __repr__(self):
        return f"<Author(author_id='{self.author_id}', name='{self.name}', department='{self.department}')>"


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
        
        # Check if authors table exists and has correct schema
        self._ensure_authors_table_schema()
        
        # Create processed tables
        Base.metadata.create_all(self.engine)
        
        session_factory = sessionmaker(bind=self.engine)
        self.Session = scoped_session(session_factory)
        self.db_path = db_path
    
    def _ensure_authors_table_schema(self):
        """Ensure authors table has the correct schema.
        
        If the old authors table exists with different columns, we drop and recreate it
        to match the new schema (id, author_id, name, title, alt_name, bio, alias, has_info, department).
        """
        try:
            with self.engine.connect() as conn:
                # Check if table exists
                result = conn.execute(text("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='authors'
                """))
                table_exists = result.fetchone() is not None
                
                if table_exists:
                    # Check if table has correct schema
                    result = conn.execute(text("PRAGMA table_info(authors)"))
                    columns = [row[1] for row in result.fetchall()]
                    
                    required_columns = {'id', 'author_id', 'name', 'title', 'alt_name', 'alias', 'department', 'location', 'tags', 'bio', 'has_info'}
                    existing_columns = set(columns)
                    
                    # If schema doesn't match, drop and recreate
                    if not required_columns.issubset(existing_columns) or 'alternate_name' in existing_columns:
                        logger.info("Authors table has old schema. Dropping and recreating with new schema...")
                        conn.execute(text("DROP TABLE IF EXISTS authors"))
                        conn.commit()
                        logger.info("Old authors table dropped. Will be recreated with correct schema.")
                    else:
                        logger.info("Authors table schema is correct")
        except Exception as e:
            logger.warning(f"Could not check/update authors table schema: {str(e)}")
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


def process_authors():
    """Process impressum authors from authors_raw to authors table."""
    logger.info("="*80)
    logger.info("01 - Processing Impressum Authors")
    logger.info("Processing authors from authors_raw to authors table")
    logger.info("="*80)
    
    # Initialize database managers
    raw_db = DatabaseManagerV3()
    processed_db = ProcessedDatabaseManager()
    
    try:
        # Get all authors from authors_raw
        raw_session = raw_db.Session()
        processed_session = processed_db.Session()
        
        try:
            all_raw_authors = raw_session.query(AuthorRaw).all()
            logger.info(f"Found {len(all_raw_authors)} authors in authors_raw table")
            
            processed_count = 0
            updated_count = 0
            error_count = 0
            
            for raw_author in all_raw_authors:
                try:
                    # Check if author already exists in processed table
                    existing_author = None
                    if raw_author.author_id:
                        existing_author = processed_session.query(Author).filter_by(
                            author_id=raw_author.author_id
                        ).first()
                    else:
                        # If no author_id, try to find by name
                        existing_author = processed_session.query(Author).filter_by(
                            name=raw_author.name,
                            author_id=None
                        ).first()
                    
                    if existing_author:
                        # Update existing author
                        existing_author.name = raw_author.name
                        existing_author.title = raw_author.title or existing_author.title
                        existing_author.alt_name = raw_author.alt_name or existing_author.alt_name
                        existing_author.alias = raw_author.alias or existing_author.alias
                        existing_author.department = raw_author.department or existing_author.department
                        existing_author.bio = raw_author.bio or existing_author.bio
                        existing_author.has_info = raw_author.has_info
                        # Keep location and tags as None (need processing)
                        updated_count += 1
                    else:
                        # Create new author
                        new_author = Author(
                            author_id=raw_author.author_id,
                            name=raw_author.name,
                            title=raw_author.title,
                            alt_name=raw_author.alt_name,
                            alias=raw_author.alias,
                            department=raw_author.department,
                            location=None,  # Empty - needs processing
                            tags=None,  # Empty - needs processing
                            bio=raw_author.bio,
                            has_info=raw_author.has_info
                        )
                        processed_session.add(new_author)
                        processed_count += 1
                    
                    # Commit every 100 records
                    if (processed_count + updated_count) % 100 == 0:
                        processed_session.commit()
                        logger.info(f"Processed {processed_count + updated_count} authors...")
                
                except Exception as e:
                    error_count += 1
                    logger.error(f"Error processing author {raw_author.id} ({raw_author.name}): {str(e)}")
                    processed_session.rollback()
                    continue
            
            # Final commit
            processed_session.commit()
            
            logger.info("="*80)
            logger.info("Processing complete!")
            logger.info("="*80)
            logger.info(f"New authors created: {processed_count}")
            logger.info(f"Existing authors updated: {updated_count}")
            logger.info(f"Errors: {error_count}")
            logger.info(f"Total processed: {processed_count + updated_count}")
            logger.info("="*80)
            logger.info("Note: location and tags columns are left empty")
            logger.info("      and will be populated by later processing steps.")
            logger.info("="*80)
            
        finally:
            raw_session.close()
            processed_session.close()
    
    finally:
        raw_db.close()
        processed_db.close()


if __name__ == '__main__':
    process_authors()

