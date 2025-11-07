"""Database models for tracking scraped NZZ articles."""
import os
import html
import re
from datetime import datetime
from typing import List, Dict
from sqlalchemy import create_engine, Column, String, DateTime, Text, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import NullPool
import threading
import logging

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
    description = Column(Text, nullable=True)  # Article description

    def __repr__(self):
        return f"<Article(article_id='{self.article_id}', title='{self.title[:50]}...')>"


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
    
    def article_exists(self, article_id: str) -> bool:
        """Check if an article has already been scraped."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                session = self.Session()  # Get thread-local session
                result = session.query(Article).filter_by(article_id=article_id).first() is not None
                return result
            except Exception as e:
                # If there's an error, try to get a fresh session
                try:
                    self.Session.remove()  # Remove potentially corrupted session
                except:
                    pass
                
                if attempt < max_retries - 1:
                    # Wait a bit before retrying
                    import time
                    time.sleep(0.1)
                    continue
                else:
                    # Last attempt failed, return False (assume article doesn't exist)
                    logger = logging.getLogger('nzz_scraper')
                    logger.warning(f"Failed to check if article {article_id} exists after {max_retries} attempts: {str(e)}")
                    return False
    
    def save_article(self, article_id: str, title: str, content: str, 
                     tags: list, article_url: str, article_date: datetime = None,
                     article_updated: datetime = None, author: str = None,
                     description: str = None, category: str = None,
                     scraped_at: datetime = None) -> Article:
        """Save a scraped article to the database."""
        session = self.Session()  # Get thread-local session
        try:
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
                description=description,
                scraped_at=scraped_at
            )
            session.add(article)
            try:
                session.commit()
            except Exception as commit_error:
                # If commit fails, rollback and try to get a fresh session
                try:
                    session.rollback()
                except:
                    pass
                # Remove the corrupted session
                try:
                    self.Session.remove()
                except:
                    pass
                raise commit_error
            return article
        except Exception as e:
            # If there's any error, try to clean up the session
            try:
                session.rollback()
            except:
                pass
            try:
                self.Session.remove()
            except:
                pass
            raise
        finally:
            # Don't remove session here - let scoped_session manage it
            # But ensure we close the session properly
            try:
                session.close()
            except:
                pass
    
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
    
    def close(self):
        """Close database session."""
        try:
            self.Session.remove()  # Remove all thread-local sessions
        except:
            pass

