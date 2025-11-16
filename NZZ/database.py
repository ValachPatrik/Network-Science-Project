"""Database models for tracking scraped NZZ articles."""
import os
import html
import re
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy import create_engine, Column, String, DateTime, Text, Integer, ForeignKey, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session, relationship
from sqlalchemy.pool import NullPool
from sqlalchemy.exc import OperationalError
import sqlite3
import threading
import logging
import time

# Get the directory where this script is located (NZZ folder)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

Base = declarative_base()


class Article(Base):
    """Model for storing scraped NZZ article data."""
    __tablename__ = 'articles'

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(String(255), unique=True, nullable=False, index=True)
    title = Column(String(500), nullable=True)
    content = Column(Text, nullable=False)
    tags = Column(String(1000), nullable=True)  # Store as comma-separated string
    category = Column(String(200), nullable=True)  # Category from URL (e.g., zuerich, wirtschaft)
    scraped_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    article_url = Column(String(500), nullable=False)
    article_date = Column(DateTime, nullable=True)  # Date from the article itself (published date)
    article_updated = Column(DateTime, nullable=True)  # Updated date if available
    author = Column(String(200), nullable=True)  # Author name
    author_ids = Column(String(500), nullable=True)  # Comma-separated list of author IDs
    description = Column(Text, nullable=True)  # Article description
    location = Column(String(200), nullable=True)  # Location associated with article (from author location, e.g., "Bangkok", "Mumbai")

    def __repr__(self):
        return f"<Article(article_id='{self.article_id}', title='{self.title[:50]}...')>"


# Association table for article-authors many-to-many relationship
article_author_association = Table(
    'article_author_association',
    Base.metadata,
    Column('article_id', Integer, ForeignKey('articles.id'), primary_key=True),
    Column('author_id', Integer, ForeignKey('authors.id'), primary_key=True)
)


class RelatedArticle(Base):
    """Model for storing related articles relationships."""
    __tablename__ = 'related_articles'

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(String(255), ForeignKey('articles.article_id'), nullable=False, index=True)
    related_article_id = Column(String(255), nullable=False, index=True)
    related_article_url = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<RelatedArticle(article_id='{self.article_id}', related_article_id='{self.related_article_id}')>"


class Author(Base):
    """Model for storing author information."""
    __tablename__ = 'authors'

    id = Column(Integer, primary_key=True, autoincrement=True)
    author_id = Column(String(255), unique=True, nullable=True, index=True)  # ID from URL (e.g., ld.1894615), nullable for authors without links
    name = Column(String(200), nullable=False)
    title = Column(String(200), nullable=True)  # Job title (e.g., "Ressortleiter Feuilleton")
    alternate_name = Column(String(100), nullable=True)  # Short name (e.g., "rb.")
    bio = Column(Text, nullable=True)  # Biography text
    image_url = Column(String(500), nullable=True)  # Profile image URL
    author_url = Column(String(500), nullable=True)  # Full URL to author profile, nullable for authors without links
    alias = Column(String(200), nullable=True)  # Manual alias (e.g., for cities like "Andreas Babst, Bangkok")
    currently_employed = Column(Integer, default=0, nullable=False)  # 1 if currently employed, 0 if not
    scraped_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Many-to-many relationship with articles
    articles = relationship('Article', secondary=article_author_association, backref='authors')

    def __repr__(self):
        author_id_str = self.author_id if self.author_id else 'no-id'
        return f"<Author(author_id='{author_id_str}', name='{self.name}')>"


class DatabaseManager:
    """Manages database connections and operations."""
    
    def __init__(self, db_path=None):
        """Initialize database connection.
        
        Args:
            db_path: Path to database file. If None, uses default path in NZZ folder.
        """
        if db_path is None:
            # Use default path in NZZ folder
            db_path = os.path.join(SCRIPT_DIR, 'nzz_scraped_articles.db')
        else:
            # If relative path, make it relative to NZZ folder
            if not os.path.isabs(db_path):
                db_path = os.path.join(SCRIPT_DIR, db_path)
        
        # Normalize path for cross-platform compatibility (especially Windows)
        db_path = os.path.normpath(db_path)
        
        # Log database path for verification
        logger = logging.getLogger('nzz_scraper')
        logger.info(f"Database path: {db_path}")
        logger.info(f"Database directory: {os.path.dirname(db_path)}")
        
        # Ensure the directory exists
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            logger.info(f"Created database directory: {db_dir}")
        
        # Use NullPool for better thread safety with SQLite
        # Each thread gets its own connection, avoiding thread-safety issues
        self.engine = create_engine(
            f'sqlite:///{db_path}',
            echo=False,
            poolclass=NullPool,
            connect_args={'check_same_thread': False}
        )
        Base.metadata.create_all(self.engine)
        # Use scoped_session for thread-safe session management
        session_factory = sessionmaker(bind=self.engine)
        self.Session = scoped_session(session_factory)
        self.session = self.Session()  # Get thread-local session
        
        # Store the database path for reference
        self.db_path = db_path
        
        # Run migrations to add new columns if they don't exist
        self._migrate_database()
    
    def _migrate_database(self):
        """Migrate database schema to add new columns if they don't exist."""
        from sqlalchemy import inspect, text
        
        logger = logging.getLogger('nzz_scraper')
        
        try:
            inspector = inspect(self.engine)
            
            # Migrate authors table
            try:
                author_columns = {col['name']: col for col in inspector.get_columns('authors')}
                
                # Add alias column if it doesn't exist
                if 'alias' not in author_columns:
                    try:
                        with self.engine.connect() as conn:
                            conn.execute(text("ALTER TABLE authors ADD COLUMN alias VARCHAR(200)"))
                            conn.commit()
                            logger.info("Added 'alias' column to authors table")
                    except Exception as e:
                        logger.warning(f"Could not add 'alias' column: {str(e)}")
                
                # Add currently_employed column if it doesn't exist
                if 'currently_employed' not in author_columns:
                    try:
                        with self.engine.connect() as conn:
                            conn.execute(text("ALTER TABLE authors ADD COLUMN currently_employed INTEGER DEFAULT 0"))
                            conn.commit()
                            logger.info("Added 'currently_employed' column to authors table")
                    except Exception as e:
                        logger.warning(f"Could not add 'currently_employed' column: {str(e)}")
                
                # Check if author_id is nullable - SQLite doesn't support ALTER COLUMN
                # So we'll use a workaround: use "no-id" as a placeholder for authors without links
                # This allows us to keep the unique constraint while supporting authors without links
                if 'author_id' in author_columns and not author_columns['author_id'].get('nullable', True):
                    logger.info("Note: author_id column is NOT NULL - using 'no-id' placeholder for authors without links")
            except Exception as e:
                logger.warning(f"Could not migrate authors table: {str(e)}")
            
            # Migrate articles table
            try:
                article_columns = {col['name']: col for col in inspector.get_columns('articles')}
                
                # Add author_ids column if it doesn't exist
                if 'author_ids' not in article_columns:
                    try:
                        with self.engine.connect() as conn:
                            conn.execute(text("ALTER TABLE articles ADD COLUMN author_ids VARCHAR(500)"))
                            conn.commit()
                            logger.info("Added 'author_ids' column to articles table")
                    except Exception as e:
                        logger.warning(f"Could not add 'author_ids' column: {str(e)}")
                
                # Add location column if it doesn't exist
                if 'location' not in article_columns:
                    try:
                        with self.engine.connect() as conn:
                            conn.execute(text("ALTER TABLE articles ADD COLUMN location VARCHAR(200)"))
                            conn.commit()
                            logger.info("Added 'location' column to articles table")
                    except Exception as e:
                        logger.warning(f"Could not add 'location' column: {str(e)}")
            except Exception as e:
                logger.warning(f"Could not migrate articles table: {str(e)}")
                
        except Exception as e:
            logger.warning(f"Could not run database migration: {str(e)}")
    
    def article_exists(self, article_id: str) -> bool:
        """Check if an article has already been scraped."""
        max_retries = 5
        base_delay = 0.1
        logger = logging.getLogger('nzz_scraper')
        
        for attempt in range(max_retries):
            session = None
            try:
                session = self.Session()  # Get thread-local session
                result = session.query(Article).filter_by(article_id=article_id).first() is not None
                return result
            except (OperationalError, sqlite3.OperationalError) as e:
                # Database is locked - retry with exponential backoff
                if session:
                    try:
                        session.rollback()
                    except:
                        pass
                    try:
                        session.close()
                    except:
                        pass
                
                # Check if it's a database locked error
                error_str = str(e).lower()
                if 'database is locked' in error_str or 'locked' in error_str:
                    if attempt < max_retries - 1:
                        # Exponential backoff: 0.1s, 0.2s, 0.4s, 0.8s, 1.6s
                        delay = base_delay * (2 ** attempt)
                        time.sleep(delay)
                        # Remove potentially corrupted session
                        try:
                            self.Session.remove()
                        except:
                            pass
                        continue
                    else:
                        # Last attempt failed, return False (assume article doesn't exist)
                        logger.warning(f"Failed to check if article {article_id} exists after {max_retries} attempts: {str(e)}")
                        return False
                else:
                    # Different OperationalError - don't retry
                    raise
            except Exception as e:
                # Other errors - try to clean up and retry once
                if session:
                    try:
                        session.rollback()
                    except:
                        pass
                    try:
                        session.close()
                    except:
                        pass
                
                try:
                    self.Session.remove()  # Remove potentially corrupted session
                except:
                    pass
                
                if attempt < max_retries - 1:
                    # Wait a bit before retrying
                    delay = base_delay * (2 ** attempt)
                    time.sleep(delay)
                    continue
                else:
                    # Last attempt failed, return False (assume article doesn't exist)
                    logger.warning(f"Failed to check if article {article_id} exists after {max_retries} attempts: {str(e)}")
                    return False
    
    def save_article(self, article_id: str, title: str, content: str, 
                     tags: list, article_url: str, article_date: datetime = None,
                     article_updated: datetime = None, author: str = None,
                     author_ids: str = None, description: str = None, 
                     category: str = None, scraped_at: datetime = None,
                     location: str = None) -> Article:
        """Save a scraped article to the database."""
        max_retries = 5
        base_delay = 0.1
        logger = logging.getLogger('nzz_scraper')
        
        for attempt in range(max_retries):
            session = None
            try:
                session = self.Session()  # Get thread-local session
                
                # Clean and truncate tags string
                tags_str = ','.join(tags) if tags else ''
                # Clean non-breaking spaces and other problematic characters
                tags_str = tags_str.replace('\xa0', ' ')  # Replace non-breaking space
                tags_str = re.sub(r'\s+', ' ', tags_str)  # Normalize whitespace
                # Truncate to fit database column (1000 chars)
                if len(tags_str) > 1000:
                    tags_str = tags_str[:997] + '...'
                
                # Clean and truncate title if needed (500 chars)
                if title:
                    title = title.replace('\xa0', ' ')  # Replace non-breaking space
                    if len(title) > 500:
                        title = title[:497] + '...'
                
                # Truncate category if needed (200 chars)
                if category and len(category) > 200:
                    category = category[:197] + '...'
                
                # Truncate author if needed (200 chars)
                if author and len(author) > 200:
                    author = author[:197] + '...'
                
                # Truncate URL if needed (500 chars)
                if article_url and len(article_url) > 500:
                    article_url = article_url[:497] + '...'
                
                # Clean description - remove HTML entities and problematic characters
                if description:
                    # Decode HTML entities (e.g., &nbsp; -> space)
                    description = html.unescape(description)
                    # Replace non-breaking spaces
                    description = description.replace('\xa0', ' ')
                    # Normalize whitespace
                    description = re.sub(r'\s+', ' ', description)
                    # Remove any remaining HTML tags if any
                    description = re.sub(r'<[^>]+>', '', description)
                
                # Use provided scraped_at or default to current time (down to the second)
                if scraped_at is None:
                    scraped_at = datetime.utcnow().replace(microsecond=0)
                
                # Truncate author_ids if needed (500 chars)
                if author_ids and len(author_ids) > 500:
                    author_ids = author_ids[:497] + '...'
                
                # Truncate location if needed (200 chars)
                if location and len(location) > 200:
                    location = location[:197] + '...'
                
                article = Article(
                    article_id=article_id,
                    title=title,
                    content=content,
                    tags=tags_str,
                    category=category,
                    article_url=article_url,
                    article_date=article_date,
                    article_updated=article_updated,
                    author=author,
                    author_ids=author_ids,
                    description=description,
                    scraped_at=scraped_at,
                    location=location
                )
                session.add(article)
                session.commit()
                return article
            except (OperationalError, sqlite3.OperationalError) as e:
                # Database is locked - retry with exponential backoff
                if session:
                    try:
                        session.rollback()
                    except:
                        pass
                    try:
                        session.close()
                    except:
                        pass
                
                # Check if it's a database locked error
                error_str = str(e).lower()
                if 'database is locked' in error_str or 'locked' in error_str:
                    if attempt < max_retries - 1:
                        # Exponential backoff: 0.1s, 0.2s, 0.4s, 0.8s, 1.6s
                        delay = base_delay * (2 ** attempt)
                        time.sleep(delay)
                        # Remove potentially corrupted session
                        try:
                            self.Session.remove()
                        except:
                            pass
                        continue
                    else:
                        # Last attempt failed
                        logger.error(f"Failed to save article {article_id} after {max_retries} attempts: {str(e)}")
                        raise
                else:
                    # Different OperationalError - don't retry
                    raise
            except Exception as e:
                # Other errors - try to clean up and retry
                if session:
                    try:
                        session.rollback()
                    except:
                        pass
                    try:
                        session.close()
                    except:
                        pass
                
                try:
                    self.Session.remove()
                except:
                    pass
                
                if attempt < max_retries - 1:
                    # Wait a bit before retrying
                    delay = base_delay * (2 ** attempt)
                    time.sleep(delay)
                    continue
                else:
                    # Last attempt failed
                    logger.error(f"Failed to save article {article_id} after {max_retries} attempts: {str(e)}")
                    raise
    
    def get_all_scraped_ids(self) -> set:
        """Get all scraped article IDs as a set."""
        session = self.Session()  # Get thread-local session
        try:
            articles = session.query(Article.article_id).all()
            return {article_id[0] for article_id in articles}
        finally:
            # Don't remove session - let scoped_session manage it
            pass
    
    def get_all_articles(self) -> List[Article]:
        """Get all scraped articles."""
        session = self.Session()  # Get thread-local session
        try:
            return session.query(Article).order_by(Article.scraped_at.desc()).all()
        finally:
            # Don't remove session - let scoped_session manage it
            pass
    
    def get_article_count(self) -> int:
        """Get total number of scraped articles."""
        session = self.Session()  # Get thread-local session
        try:
            return session.query(Article).count()
        finally:
            # Don't remove session - let scoped_session manage it
            pass
    
    def get_oldest_article_date(self) -> datetime:
        """Get the oldest article date (article_date field) from the database.
        
        Returns:
            datetime: The oldest article_date, or None if no articles with dates exist.
        """
        session = self.Session()  # Get thread-local session
        try:
            # Query for the oldest article_date (not scraped_at)
            oldest = session.query(Article.article_date).filter(
                Article.article_date.isnot(None)
            ).order_by(Article.article_date.asc()).first()
            
            if oldest and oldest[0]:
                return oldest[0]
            return None
        finally:
            # Don't remove session - let scoped_session manage it
            pass
    
    def get_oldest_articles(self, limit: int = 10) -> List[Article]:
        """Get the oldest articles ordered by article_date.
        
        Args:
            limit: Number of articles to return (default: 10)
        
        Returns:
            List[Article]: List of articles ordered by article_date (oldest first)
        """
        session = self.Session()  # Get thread-local session
        try:
            return session.query(Article).filter(
                Article.article_date.isnot(None)
            ).order_by(Article.article_date.asc()).limit(limit).all()
        finally:
            # Don't remove session - let scoped_session manage it
            pass
    
    def get_article_by_id(self, article_id: str) -> Article:
        """Get an article by its article_id.
        
        Args:
            article_id: The article ID to search for
        
        Returns:
            Article: The article if found, None otherwise
        """
        max_retries = 5
        base_delay = 0.1
        logger = logging.getLogger('nzz_scraper')
        
        for attempt in range(max_retries):
            session = None
            try:
                session = self.Session()  # Get thread-local session
                return session.query(Article).filter_by(article_id=article_id).first()
            except (OperationalError, sqlite3.OperationalError) as e:
                # Database is locked - retry with exponential backoff
                if session:
                    try:
                        session.rollback()
                    except:
                        pass
                    try:
                        session.close()
                    except:
                        pass
                
                # Check if it's a database locked error
                error_str = str(e).lower()
                if 'database is locked' in error_str or 'locked' in error_str:
                    if attempt < max_retries - 1:
                        # Exponential backoff: 0.1s, 0.2s, 0.4s, 0.8s, 1.6s
                        delay = base_delay * (2 ** attempt)
                        time.sleep(delay)
                        # Remove potentially corrupted session
                        try:
                            self.Session.remove()
                        except:
                            pass
                        continue
                    else:
                        # Last attempt failed
                        logger.error(f"Failed to get article {article_id} after {max_retries} attempts: {str(e)}")
                        raise
                else:
                    # Different OperationalError - don't retry
                    raise
            except Exception as e:
                # Other errors - try to clean up and retry
                if session:
                    try:
                        session.rollback()
                    except:
                        pass
                    try:
                        session.close()
                    except:
                        pass
                
                try:
                    self.Session.remove()
                except:
                    pass
                
                if attempt < max_retries - 1:
                    # Wait a bit before retrying
                    delay = base_delay * (2 ** attempt)
                    time.sleep(delay)
                    continue
                else:
                    # Last attempt failed
                    logger.error(f"Failed to get article {article_id} after {max_retries} attempts: {str(e)}")
                    raise
    
    def delete_article_by_id(self, article_id: str) -> bool:
        """Delete an article by its article_id.
        
        Args:
            article_id: The article ID to delete
        
        Returns:
            bool: True if article was deleted, False if not found
        """
        session = self.Session()  # Get thread-local session
        try:
            article = session.query(Article).filter_by(article_id=article_id).first()
            if article:
                session.delete(article)
                session.commit()
                return True
            return False
        except Exception as e:
            session.rollback()
            raise
        finally:
            # Don't remove session - let scoped_session manage it
            pass
    
    def delete_articles_by_ids(self, article_ids: List[str]) -> int:
        """Delete multiple articles by their article_ids.
        
        Args:
            article_ids: List of article IDs to delete
        
        Returns:
            int: Number of articles deleted
        """
        session = self.Session()  # Get thread-local session
        try:
            deleted_count = session.query(Article).filter(
                Article.article_id.in_(article_ids)
            ).delete(synchronize_session=False)
            session.commit()
            return deleted_count
        except Exception as e:
            session.rollback()
            raise
        finally:
            # Don't remove session - let scoped_session manage it
            pass
    
    def verify_article_format(self, article: Article) -> Dict[str, bool]:
        """Verify that an article has proper format."""
        checks = {
            'has_id': bool(article.article_id and article.article_id.strip()),
            'has_title': bool(article.title and article.title.strip()),
            'has_content': bool(article.content and len(article.content.strip()) > 50),
            'has_url': bool(article.article_url and article.article_url.strip()),
            'has_scraped_at': bool(article.scraped_at),
        }
        checks['all_valid'] = all(checks.values())
        return checks
    
    def save_related_article(self, article_id: str, related_article_id: str, related_article_url: str) -> RelatedArticle:
        """Save a related article relationship with retry logic for database locking.
        
        Args:
            article_id: The ID of the main article
            related_article_id: The ID of the related article
            related_article_url: The URL of the related article
            
        Returns:
            RelatedArticle: The saved related article relationship
        """
        max_retries = 5
        base_delay = 0.1  # Start with 100ms delay
        
        for attempt in range(max_retries):
            session = self.Session()
            try:
                # Check if relationship already exists
                existing = session.query(RelatedArticle).filter_by(
                    article_id=article_id,
                    related_article_id=related_article_id
                ).first()
                
                if existing:
                    return existing
                
                # Truncate URL if needed
                if len(related_article_url) > 500:
                    related_article_url = related_article_url[:497] + '...'
                
                related_article = RelatedArticle(
                    article_id=article_id,
                    related_article_id=related_article_id,
                    related_article_url=related_article_url
                )
                session.add(related_article)
                session.commit()
                return related_article
            except (OperationalError, sqlite3.OperationalError) as e:
                # Database is locked - retry with exponential backoff
                session.rollback()
                try:
                    session.close()
                except:
                    pass
                
                # Check if it's a database locked error
                error_str = str(e).lower()
                if 'database is locked' in error_str or 'locked' in error_str:
                    if attempt < max_retries - 1:
                        # Exponential backoff: 0.1s, 0.2s, 0.4s, 0.8s, 1.6s
                        delay = base_delay * (2 ** attempt)
                        time.sleep(delay)
                        # Remove potentially corrupted session
                        try:
                            self.Session.remove()
                        except:
                            pass
                        continue
                    else:
                        # Last attempt failed
                        logger = logging.getLogger('nzz_scraper')
                        logger.error(f"Failed to save related article {related_article_id} after {max_retries} attempts: {str(e)}")
                        raise
                else:
                    # Different OperationalError - don't retry
                    raise
            except Exception as e:
                session.rollback()
                try:
                    session.close()
                except:
                    pass
                raise
            finally:
                # Ensure session is closed even if no exception
                try:
                    session.close()
                except:
                    pass
    
    def author_exists(self, author_id: str = None, name: str = None, alias: str = None) -> bool:
        """Check if an author already exists in the database.
        
        Checks against the name field and all values in the alias field (if alias contains
        comma-separated values, each one is checked individually).
        
        Args:
            author_id: The author ID to check (optional)
            name: The author name to check (optional, used when author_id is None)
            alias: The author alias to check (optional, used to find authors by alias)
            
        Returns:
            bool: True if author exists, False otherwise
        """
        max_retries = 5
        base_delay = 0.1
        logger = logging.getLogger('nzz_scraper')
        
        for attempt in range(max_retries):
            session = None
            try:
                session = self.Session()
                if author_id:
                    result = session.query(Author).filter_by(author_id=author_id).first() is not None
                    if result:
                        return True
                
                # Check by name (for authors without ID)
                if name:
                    name_lower = name.lower().strip()
                    # Check exact name match (including authors with placeholder IDs)
                    result = session.query(Author).filter_by(name=name).first() is not None
                    if result:
                        return True
                    # Check case-insensitive name match
                    all_authors = session.query(Author).all()
                    for author in all_authors:
                        if author.name and author.name.lower() == name_lower:
                            return True
                        # Check if name matches any alias (including comma-separated aliases)
                        if author.alias:
                            # Split alias by comma and check each one
                            alias_parts = [a.strip().lower() for a in author.alias.split(',')]
                            if name_lower in alias_parts:
                                return True
                
                # Check by alias
                if alias:
                    alias_lower = alias.lower().strip()
                    # Check exact alias match
                    result = session.query(Author).filter_by(alias=alias).first() is not None
                    if result:
                        return True
                    # Check if alias matches any name
                    result = session.query(Author).filter(Author.name == alias).first() is not None
                    if result:
                        return True
                    # Check case-insensitive name match
                    all_authors = session.query(Author).all()
                    for author in all_authors:
                        if author.name and author.name.lower() == alias_lower:
                            return True
                        # Check if alias matches any alias value (including comma-separated aliases)
                        if author.alias:
                            # Split alias by comma and check each one
                            alias_parts = [a.strip().lower() for a in author.alias.split(',')]
                            if alias_lower in alias_parts:
                                return True
                
                return False
            except (OperationalError, sqlite3.OperationalError) as e:
                # Database is locked - retry with exponential backoff
                if session:
                    try:
                        session.rollback()
                    except:
                        pass
                    try:
                        session.close()
                    except:
                        pass
                
                # Check if it's a database locked error
                error_str = str(e).lower()
                if 'database is locked' in error_str or 'locked' in error_str:
                    if attempt < max_retries - 1:
                        # Exponential backoff: 0.1s, 0.2s, 0.4s, 0.8s, 1.6s
                        delay = base_delay * (2 ** attempt)
                        time.sleep(delay)
                        # Remove potentially corrupted session
                        try:
                            self.Session.remove()
                        except:
                            pass
                        continue
                    else:
                        # Last attempt failed, return False (assume author doesn't exist)
                        logger.warning(f"Failed to check if author exists after {max_retries} attempts: {str(e)}")
                        return False
                else:
                    # Different OperationalError - don't retry
                    raise
            except Exception as e:
                # Other errors - try to clean up and retry
                if session:
                    try:
                        session.rollback()
                    except:
                        pass
                    try:
                        session.close()
                    except:
                        pass
                
                try:
                    self.Session.remove()
                except:
                    pass
                
                if attempt < max_retries - 1:
                    # Wait a bit before retrying
                    delay = base_delay * (2 ** attempt)
                    time.sleep(delay)
                    continue
                else:
                    # Last attempt failed, return False (assume author doesn't exist)
                    logger.warning(f"Failed to check if author exists after {max_retries} attempts: {str(e)}")
                    return False
    
    def get_author_by_name_or_alias(self, name: str = None, alias: str = None) -> Optional[Author]:
        """Get an author by name or alias with retry logic for database locking.
        
        Checks against the name field and all values in the alias field (if alias contains
        comma-separated values, each one is checked individually).
        
        Args:
            name: The author name to search for (optional)
            alias: The author alias to search for (optional)
            
        Returns:
            Author if found, None otherwise
        """
        max_retries = 5
        base_delay = 0.1  # Start with 100ms delay
        
        for attempt in range(max_retries):
            session = self.Session()
            try:
                if name:
                    name_lower = name.lower().strip()
                    # Check exact name match
                    author = session.query(Author).filter_by(name=name).first()
                    if author:
                        return author
                    # Check case-insensitive name match
                    all_authors = session.query(Author).all()
                    for author in all_authors:
                        if author.name and author.name.lower() == name_lower:
                            return author
                        # Check if name matches any alias (including comma-separated aliases)
                        if author.alias:
                            # Split alias by comma and check each one
                            alias_parts = [a.strip().lower() for a in author.alias.split(',')]
                            if name_lower in alias_parts:
                                return author
                
                if alias:
                    alias_lower = alias.lower().strip()
                    # Check exact alias match
                    author = session.query(Author).filter_by(alias=alias).first()
                    if author:
                        return author
                    # Check if alias matches any name
                    author = session.query(Author).filter(Author.name == alias).first()
                    if author:
                        return author
                    # Check case-insensitive name match
                    all_authors = session.query(Author).all()
                    for author in all_authors:
                        if author.name and author.name.lower() == alias_lower:
                            return author
                        # Check if alias matches any alias value (including comma-separated aliases)
                        if author.alias:
                            # Split alias by comma and check each one
                            alias_parts = [a.strip().lower() for a in author.alias.split(',')]
                            if alias_lower in alias_parts:
                                return author
                
                return None
            except (OperationalError, sqlite3.OperationalError) as e:
                # Database is locked - retry with exponential backoff
                try:
                    session.close()
                except:
                    pass
                
                # Check if it's a database locked error
                error_str = str(e).lower()
                if 'database is locked' in error_str or 'locked' in error_str:
                    if attempt < max_retries - 1:
                        # Exponential backoff: 0.1s, 0.2s, 0.4s, 0.8s, 1.6s
                        delay = base_delay * (2 ** attempt)
                        time.sleep(delay)
                        # Remove potentially corrupted session
                        try:
                            self.Session.remove()
                        except:
                            pass
                        continue
                    else:
                        # Last attempt failed
                        logger = logging.getLogger('nzz_scraper')
                        logger.warning(f"Failed to get author by name/alias after {max_retries} attempts: {str(e)}")
                        return None
                else:
                    # Different OperationalError - don't retry
                    logger = logging.getLogger('nzz_scraper')
                    logger.warning(f"Failed to get author by name/alias: {str(e)}")
                    return None
            except Exception as e:
                logger = logging.getLogger('nzz_scraper')
                logger.warning(f"Failed to get author by name/alias: {str(e)}")
                return None
            finally:
                try:
                    session.close()
                except:
                    pass
    
    def save_author(self, name: str, author_id: str = None, author_url: str = None, 
                    title: str = None, alternate_name: str = None,
                    bio: str = None, image_url: str = None, alias: str = None,
                    currently_employed: int = 0) -> Author:
        """Save an author to the database with retry logic for database locking.
        
        Args:
            name: The author's full name (required)
            author_id: The author ID (extracted from URL, optional for authors without links)
            author_url: The full URL to the author profile (optional for authors without links)
            title: Job title (optional)
            alternate_name: Short name/abbreviation (optional)
            bio: Biography text (optional)
            image_url: Profile image URL (optional)
            alias: Manual alias (optional, e.g., for cities)
            currently_employed: 1 if currently employed, 0 if not (default: 0)
            
        Returns:
            Author: The saved author
        """
        max_retries = 5
        base_delay = 0.1  # Start with 100ms delay
        
        for attempt in range(max_retries):
            session = self.Session()
            try:
                # Workaround for SQLite: if author_id is None and column is NOT NULL,
                # use a placeholder value "no-id-{name_hash}" to maintain uniqueness
                # We'll use a hash of the name to ensure uniqueness
                if author_id is None:
                    import hashlib
                    name_hash = hashlib.md5(name.encode('utf-8')).hexdigest()[:8]
                    placeholder_id = f"no-id-{name_hash}"
                else:
                    placeholder_id = author_id
                
                # Workaround for SQLite: if author_url is None and column is NOT NULL,
                # use a placeholder value
                if author_url is None:
                    placeholder_url = f"no-url-{placeholder_id}"
                else:
                    placeholder_url = author_url
                
                # Check if author already exists
                if author_id:
                    existing = session.query(Author).filter_by(author_id=author_id).first()
                else:
                    # For authors without ID, check by name and placeholder_id
                    existing = session.query(Author).filter_by(name=name, author_id=placeholder_id).first()
                    if not existing:
                        # Also check by name only (in case of old records)
                        existing = session.query(Author).filter_by(name=name).filter(Author.author_id.like('no-id-%')).first()
                
                if existing:
                    # Update existing author
                    if name:
                        existing.name = name[:200] if len(name) <= 200 else name[:197] + '...'
                    if title:
                        existing.title = title[:200] if len(title) <= 200 else title[:197] + '...'
                    if alternate_name:
                        existing.alternate_name = alternate_name[:100] if len(alternate_name) <= 100 else alternate_name[:97] + '...'
                    if bio:
                        # Clean bio
                        bio = html.unescape(bio)
                        bio = bio.replace('\xa0', ' ')
                        bio = re.sub(r'\s+', ' ', bio)
                        existing.bio = bio
                    if image_url:
                        existing.image_url = image_url[:500] if len(image_url) <= 500 else image_url[:497] + '...'
                    if author_url:
                        existing.author_url = author_url[:500] if len(author_url) <= 500 else author_url[:497] + '...'
                    # Update alias to include name if not already there
                    alias_list = []
                    if existing.alias:
                        alias_list = [a.strip() for a in existing.alias.split(',')]
                    if name not in alias_list:
                        alias_list.insert(0, name)  # Add name at the beginning
                    if alias:
                        alias_parts = [a.strip() for a in alias.split(',')]
                        for alias_part in alias_parts:
                            if alias_part and alias_part not in alias_list:
                                alias_list.append(alias_part)
                    existing.alias = ', '.join(alias_list)[:200] if len(', '.join(alias_list)) <= 200 else ', '.join(alias_list)[:197] + '...'
                    
                    if currently_employed is not None:
                        existing.currently_employed = currently_employed
                    session.commit()
                    return existing
                
                # Truncate fields if needed
                if len(name) > 200:
                    name = name[:197] + '...'
                if title and len(title) > 200:
                    title = title[:197] + '...'
                if alternate_name and len(alternate_name) > 100:
                    alternate_name = alternate_name[:97] + '...'
                if bio:
                    bio = html.unescape(bio)
                    bio = bio.replace('\xa0', ' ')
                    bio = re.sub(r'\s+', ' ', bio)
                if image_url and len(image_url) > 500:
                    image_url = image_url[:497] + '...'
                if author_url and len(author_url) > 500:
                    author_url = author_url[:497] + '...'
                if alias and len(alias) > 200:
                    alias = alias[:197] + '...'
                
                # Add name to alias list if not already there
                alias_list = []
                if alias:
                    alias_list = [a.strip() for a in alias.split(',')]
                if name not in alias_list:
                    alias_list.insert(0, name)  # Add name at the beginning
                final_alias = ', '.join(alias_list)
                if len(final_alias) > 200:
                    final_alias = final_alias[:197] + '...'
                
                author = Author(
                    author_id=placeholder_id,
                    name=name,
                    title=title,
                    alternate_name=alternate_name,
                    bio=bio,
                    image_url=image_url,
                    author_url=placeholder_url,
                    alias=final_alias,
                    currently_employed=currently_employed
                )
                session.add(author)
                session.commit()
                return author
            except (OperationalError, sqlite3.OperationalError) as e:
                # Database is locked - retry with exponential backoff
                session.rollback()
                try:
                    session.close()
                except:
                    pass
                
                # Check if it's a database locked error
                error_str = str(e).lower()
                if 'database is locked' in error_str or 'locked' in error_str:
                    if attempt < max_retries - 1:
                        # Exponential backoff: 0.1s, 0.2s, 0.4s, 0.8s, 1.6s
                        delay = base_delay * (2 ** attempt)
                        time.sleep(delay)
                        # Remove potentially corrupted session
                        try:
                            self.Session.remove()
                        except:
                            pass
                        continue
                    else:
                        # Last attempt failed
                        logger = logging.getLogger('nzz_scraper')
                        logger.error(f"Failed to save author {name} after {max_retries} attempts: {str(e)}")
                        raise
                else:
                    # Different OperationalError - don't retry
                    raise
            except Exception as e:
                session.rollback()
                try:
                    session.close()
                except:
                    pass
                raise
            finally:
                # Ensure session is closed even if no exception
                try:
                    session.close()
                except:
                    pass
    
    def link_article_to_author(self, article_id: str, author_id: str) -> bool:
        """Link an article to an author using the association table.
        
        Args:
            article_id: The article ID (string, not integer)
            author_id: The author ID (string, not integer)
            
        Returns:
            bool: True if link was created, False if already exists
        """
        max_retries = 5
        base_delay = 0.1
        logger = logging.getLogger('nzz_scraper')
        
        for attempt in range(max_retries):
            session = None
            try:
                session = self.Session()
                # Get article and author by their string IDs
                article = session.query(Article).filter_by(article_id=article_id).first()
                author = session.query(Author).filter_by(author_id=author_id).first()
                
                if not article or not author:
                    return False
                
                # Check if link already exists
                if author in article.authors:
                    return False
                
                # Add relationship
                article.authors.append(author)
                session.commit()
                return True
            except (OperationalError, sqlite3.OperationalError) as e:
                # Database is locked - retry with exponential backoff
                if session:
                    try:
                        session.rollback()
                    except:
                        pass
                    try:
                        session.close()
                    except:
                        pass
                
                # Check if it's a database locked error
                error_str = str(e).lower()
                if 'database is locked' in error_str or 'locked' in error_str:
                    if attempt < max_retries - 1:
                        # Exponential backoff: 0.1s, 0.2s, 0.4s, 0.8s, 1.6s
                        delay = base_delay * (2 ** attempt)
                        time.sleep(delay)
                        # Remove potentially corrupted session
                        try:
                            self.Session.remove()
                        except:
                            pass
                        continue
                    else:
                        # Last attempt failed
                        logger.error(f"Failed to link article {article_id} to author {author_id} after {max_retries} attempts: {str(e)}")
                        raise
                else:
                    # Different OperationalError - don't retry
                    raise
            except Exception as e:
                # Other errors - try to clean up and retry
                if session:
                    try:
                        session.rollback()
                    except:
                        pass
                    try:
                        session.close()
                    except:
                        pass
                
                try:
                    self.Session.remove()
                except:
                    pass
                
                if attempt < max_retries - 1:
                    # Wait a bit before retrying
                    delay = base_delay * (2 ** attempt)
                    time.sleep(delay)
                    continue
                else:
                    # Last attempt failed
                    logger.error(f"Failed to link article {article_id} to author {author_id} after {max_retries} attempts: {str(e)}")
                    raise
    
    def get_author_by_id(self, author_id: str) -> Author:
        """Get an author by their author_id.
        
        Args:
            author_id: The author ID to search for
            
        Returns:
            Author: The author if found, None otherwise
        """
        session = self.Session()
        try:
            return session.query(Author).filter_by(author_id=author_id).first()
        finally:
            try:
                session.close()
            except:
                pass
    
    def get_related_articles(self, article_id: str) -> List[RelatedArticle]:
        """Get all related articles for a given article.
        
        Args:
            article_id: The article ID to get related articles for
            
        Returns:
            List[RelatedArticle]: List of related articles
        """
        session = self.Session()
        try:
            return session.query(RelatedArticle).filter_by(article_id=article_id).all()
        finally:
            try:
                session.close()
            except:
                pass
    
    def clean_database(self, clean_articles: bool = False, clean_authors: bool = False, 
                       clean_related_articles: bool = False, clean_article_author_associations: bool = False):
        """Clean the database by removing data from specified tables.
        
        Args:
            clean_articles: If True, delete all articles (default: False)
            clean_authors: If True, delete all authors (default: False)
            clean_related_articles: If True, delete all related articles (default: False)
            clean_article_author_associations: If True, delete all article-author associations (default: False)
        """
        session = self.Session()
        try:
            deleted_counts = {}
            
            # Delete article-author associations first (foreign key constraints)
            if clean_article_author_associations:
                from sqlalchemy import text
                deleted_counts['article_author_associations'] = session.execute(
                    text("DELETE FROM article_author_association")
                ).rowcount
            else:
                deleted_counts['article_author_associations'] = 0
            
            # Delete related articles (foreign key constraints)
            if clean_related_articles:
                deleted_counts['related_articles'] = session.query(RelatedArticle).delete()
            else:
                deleted_counts['related_articles'] = 0
            
            # Delete articles if requested
            if clean_articles:
                deleted_counts['articles'] = session.query(Article).delete()
            else:
                deleted_counts['articles'] = 0
            
            # Delete authors if requested
            if clean_authors:
                deleted_counts['authors'] = session.query(Author).delete()
            else:
                deleted_counts['authors'] = 0
            
            session.commit()
            
            logger = logging.getLogger('nzz_scraper')
            logger.info(f"Database cleaned: {deleted_counts}")
            
            return deleted_counts
        except Exception as e:
            session.rollback()
            logger = logging.getLogger('nzz_scraper')
            logger.error(f"Error cleaning database: {str(e)}", exc_info=True)
            raise
        finally:
            try:
                session.close()
            except:
                pass
    
    def clean_test_data(self, article_ids: List[str] = None):
        """Clean test data from the database.
        
        Args:
            article_ids: List of article IDs to delete. If None, deletes all test-related data.
        """
        session = self.Session()
        try:
            deleted_counts = {}
            
            if article_ids:
                # Delete specific articles and their related data
                # Delete related articles
                deleted_counts['related_articles'] = session.query(RelatedArticle).filter(
                    RelatedArticle.article_id.in_(article_ids)
                ).delete(synchronize_session=False)
                
                # Delete article-author associations
                from sqlalchemy import text
                article_id_placeholders = ','.join([f"'{aid}'" for aid in article_ids])
                deleted_counts['article_author_associations'] = session.execute(
                    text(f"DELETE FROM article_author_association WHERE article_id IN (SELECT id FROM articles WHERE article_id IN ({article_id_placeholders}))")
                ).rowcount
                
                # Delete articles
                deleted_counts['articles'] = session.query(Article).filter(
                    Article.article_id.in_(article_ids)
                ).delete(synchronize_session=False)
            else:
                # Clean all test-related data (relationships)
                deleted_counts['related_articles'] = session.query(RelatedArticle).delete()
                from sqlalchemy import text
                deleted_counts['article_author_associations'] = session.execute(
                    text("DELETE FROM article_author_association")
                ).rowcount
            
            session.commit()
            
            logger = logging.getLogger('nzz_scraper')
            logger.info(f"Test data cleaned: {deleted_counts}")
            
            return deleted_counts
        except Exception as e:
            session.rollback()
            logger = logging.getLogger('nzz_scraper')
            logger.error(f"Error cleaning test data: {str(e)}", exc_info=True)
            raise
        finally:
            try:
                session.close()
            except:
                pass
    
    def close(self):
        """Close database session."""
        try:
            self.Session.remove()  # Remove all thread-local sessions
        except:
            pass

