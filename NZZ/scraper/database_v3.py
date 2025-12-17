"""Database models for NZZ scraper v3 with raw tables."""

import os
import html
import re
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy import (
    create_engine,
    Column,
    String,
    DateTime,
    Text,
    Integer,
    ForeignKey,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import NullPool
import logging

# Get the directory where this script is located (NZZ folder)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

Base = declarative_base()


class AuthorRaw(Base):
    """Raw author data before LLM processing."""

    __tablename__ = "authors_raw"

    id = Column(Integer, primary_key=True, autoincrement=True)
    author_id = Column(
        String(255), unique=True, nullable=True, index=True
    )  # ID from URL or temp ID (unique when not null)
    name = Column(String(200), nullable=False)
    title = Column(String(200), nullable=True)  # Job title
    alt_name = Column(String(100), nullable=True)  # Short name (e.g., "rb.")
    bio = Column(Text, nullable=True)  # Biography text
    author_url = Column(String(500), nullable=True)  # Full URL to author profile
    alias = Column(String(200), nullable=True)  # Manual alias
    has_info = Column(Integer, default=0, nullable=False)  # 1 if page exists, 0 if not
    department = Column(String(200), nullable=True)  # Department from impressum
    scraped_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<AuthorRaw(author_id='{self.author_id}', name='{self.name}', department='{self.department}')>"


class ArticleRaw(Base):
    """Raw article data before LLM processing."""

    __tablename__ = "articles_raw"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(String(255), unique=True, nullable=False, index=True)
    title = Column(String(500), nullable=True)
    content = Column(Text, nullable=False)
    tags = Column(String(1000), nullable=True)  # Comma-separated string
    category = Column(String(200), nullable=True)  # Category from URL
    scraped_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    article_url = Column(String(500), nullable=False)
    article_date = Column(DateTime, nullable=True)  # Published date
    article_updated = Column(DateTime, nullable=True)  # Updated date
    author = Column(String(500), nullable=True)  # Plain author string to be processed
    author_links = Column(Text, nullable=True)  # JSON string of all author links
    description = Column(Text, nullable=True)  # Article description
    related_articles = Column(Text, nullable=True)  # JSON string of related article IDs

    def __repr__(self):
        return f"<ArticleRaw(article_id='{self.article_id}', title='{self.title[:50]}...')>"


class DatabaseManagerV3:
    """Manages database connections and operations for v3 raw tables."""

    def __init__(self, db_path=None):
        """Initialize database connection.

        Args:
            db_path: Path to database file. If None, uses default path in NZZ folder.
        """
        if db_path is None:
            db_path = os.path.join(SCRIPT_DIR, "nzz_scraped_articles.db")
        else:
            if not os.path.isabs(db_path):
                db_path = os.path.join(SCRIPT_DIR, db_path)

        db_path = os.path.normpath(db_path)

        logger = logging.getLogger("nzz_scraper")
        logger.info(f"Database path: {db_path}")

        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        self.engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            poolclass=NullPool,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)

        # Ensure unique constraints are enforced
        self._ensure_unique_constraints()

        session_factory = sessionmaker(bind=self.engine)
        self.Session = scoped_session(session_factory)
        self.session = self.Session()
        self.db_path = db_path

    def close(self):
        """Close database connections."""
        try:
            if hasattr(self, "session") and self.session:
                self.session.close()
            if hasattr(self, "Session") and self.Session:
                self.Session.remove()
            if hasattr(self, "engine") and self.engine:
                self.engine.dispose()
        except Exception as e:
            logger = logging.getLogger("nzz_scraper")
            logger.warning(f"Error closing database connections: {str(e)}")

    def _ensure_unique_constraints(self):
        """Ensure unique constraints are properly set up in the database."""
        from sqlalchemy import text

        logger = logging.getLogger("nzz_scraper")

        try:
            with self.engine.connect() as conn:
                # Check existing indexes
                result = conn.execute(
                    text(
                        """
                    SELECT name FROM sqlite_master 
                    WHERE type='index' 
                    AND (name LIKE '%article_id%' OR name LIKE '%author_id%')
                """
                    )
                )
                indexes = [row[0] for row in result]

                # Create unique index for author_id if it doesn't exist
                # SQLite allows multiple NULLs in unique columns, which is what we want
                if not any("author_id" in idx for idx in indexes):
                    try:
                        # Try with WHERE clause (SQLite 3.8.0+)
                        conn.execute(
                            text(
                                """
                            CREATE UNIQUE INDEX IF NOT EXISTS idx_authors_raw_author_id_unique 
                            ON authors_raw(author_id) 
                            WHERE author_id IS NOT NULL
                        """
                            )
                        )
                        conn.commit()
                        logger.info(
                            "Created unique index on authors_raw.author_id (with WHERE clause)"
                        )
                    except Exception:
                        # Fall back to regular unique index (allows multiple NULLs in SQLite)
                        try:
                            conn.execute(
                                text(
                                    """
                                CREATE UNIQUE INDEX IF NOT EXISTS idx_authors_raw_author_id_unique 
                                ON authors_raw(author_id)
                            """
                                )
                            )
                            conn.commit()
                            logger.info(
                                "Created unique index on authors_raw.author_id (allows multiple NULLs)"
                            )
                        except Exception as e2:
                            logger.debug(
                                f"Could not create unique index on author_id: {str(e2)}"
                            )

        except Exception as e:
            logger.debug(f"Could not ensure unique constraints: {str(e)}")
            # Continue anyway - the Column unique=True should handle it

    def save_author_raw(
        self,
        author_id: Optional[str],
        name: str,
        title: Optional[str] = None,
        alt_name: Optional[str] = None,
        bio: Optional[str] = None,
        author_url: Optional[str] = None,
        alias: Optional[str] = None,
        has_info: int = 0,
        department: Optional[str] = None,
    ) -> AuthorRaw:
        """Save raw author data to database.

        Args:
            author_id: Author ID from URL or temp ID
            name: Author name
            title: Job title
            alt_name: Alternate name/abbreviation
            bio: Biography
            author_url: Author profile URL
            alias: Alias names
            has_info: 1 if page exists, 0 if not
            department: Department from impressum

        Returns:
            Saved AuthorRaw object
        """
        session = self.Session()
        try:
            # Check if author already exists (prioritize author_id for uniqueness)
            existing = None
            if author_id:
                # First check by author_id (unique constraint)
                existing = (
                    session.query(AuthorRaw).filter_by(author_id=author_id).first()
                )
                if existing:
                    # Update existing author with same author_id
                    existing.name = name  # Update name in case it changed
                    existing.title = title or existing.title
                    existing.alt_name = alt_name or existing.alt_name
                    existing.bio = bio or existing.bio
                    existing.author_url = author_url or existing.author_url
                    existing.alias = alias or existing.alias
                    existing.has_info = has_info
                    existing.department = department or existing.department
                    existing.scraped_at = datetime.utcnow()
                    session.commit()
                    return existing

            # If no author_id or not found by author_id, check by name (for authors without IDs)
            if not author_id:
                existing = (
                    session.query(AuthorRaw)
                    .filter_by(name=name, author_id=None)
                    .first()
                )
                if existing:
                    # Update existing author without ID
                    existing.title = title or existing.title
                    existing.alt_name = alt_name or existing.alt_name
                    existing.bio = bio or existing.bio
                    existing.author_url = author_url or existing.author_url
                    existing.alias = alias or existing.alias
                    existing.has_info = has_info
                    existing.department = department or existing.department
                    existing.scraped_at = datetime.utcnow()
                    session.commit()
                    return existing

            # Create new author (no existing author found)
            author = AuthorRaw(
                author_id=author_id,
                name=name,
                title=title,
                alt_name=alt_name,
                bio=bio,
                author_url=author_url,
                alias=alias,
                has_info=has_info,
                department=department,
                scraped_at=datetime.utcnow(),
            )
            session.add(author)
            session.commit()
            return author
        except Exception as e:
            session.rollback()
            logger = logging.getLogger("nzz_scraper")
            # Check if it's a unique constraint violation
            error_str = str(e).lower()
            if "unique" in error_str or "duplicate" in error_str:
                # Try to find existing author and update it
                try:
                    if author_id:
                        existing = (
                            session.query(AuthorRaw)
                            .filter_by(author_id=author_id)
                            .first()
                        )
                        if existing:
                            existing.name = name
                            existing.title = title or existing.title
                            existing.alt_name = alt_name or existing.alt_name
                            existing.bio = bio or existing.bio
                            existing.author_url = author_url or existing.author_url
                            existing.alias = alias or existing.alias
                            existing.has_info = has_info
                            existing.department = department or existing.department
                            existing.scraped_at = datetime.utcnow()
                            session.commit()
                            return existing
                except:
                    pass
            logger.error(f"Error saving author raw: {str(e)}")
            raise
        finally:
            session.close()

    def save_article_raw(
        self,
        article_id: str,
        title: str,
        content: str,
        tags: Optional[str] = None,
        category: Optional[str] = None,
        article_url: str = None,
        article_date: Optional[datetime] = None,
        article_updated: Optional[datetime] = None,
        author: Optional[str] = None,
        author_links: Optional[str] = None,
        description: Optional[str] = None,
        related_articles: Optional[str] = None,
    ) -> ArticleRaw:
        """Save raw article data to database.

        Args:
            article_id: Article ID
            title: Article title
            content: Article content
            tags: Comma-separated tags
            category: Category from URL
            article_url: Article URL
            article_date: Published date
            article_updated: Updated date
            author: Plain author string
            author_links: JSON string of author links
            description: Article description
            related_articles: JSON string of related article IDs

        Returns:
            Saved ArticleRaw object
        """
        session = self.Session()
        try:
            # Check if article already exists (article_id has unique constraint)
            existing = (
                session.query(ArticleRaw).filter_by(article_id=article_id).first()
            )

            if existing:
                # Update existing article
                existing.title = title
                existing.content = content
                existing.tags = tags or existing.tags
                existing.category = category or existing.category
                existing.article_url = article_url or existing.article_url
                existing.article_date = article_date or existing.article_date
                existing.article_updated = article_updated or existing.article_updated
                existing.author = author or existing.author
                existing.author_links = author_links or existing.author_links
                existing.description = description or existing.description
                existing.related_articles = (
                    related_articles or existing.related_articles
                )
                existing.scraped_at = datetime.utcnow()
                session.commit()
                return existing
            else:
                # Create new article
                article = ArticleRaw(
                    article_id=article_id,
                    title=title,
                    content=content,
                    tags=tags,
                    category=category,
                    article_url=article_url or "",
                    article_date=article_date,
                    article_updated=article_updated,
                    author=author,
                    author_links=author_links,
                    description=description,
                    related_articles=related_articles,
                    scraped_at=datetime.utcnow(),
                )
                session.add(article)
                session.commit()
                return article
        except Exception as e:
            session.rollback()
            logger = logging.getLogger("nzz_scraper")
            # Check if it's a unique constraint violation
            error_str = str(e).lower()
            if "unique" in error_str or "duplicate" in error_str:
                # Try to find existing article and update it
                try:
                    existing = (
                        session.query(ArticleRaw)
                        .filter_by(article_id=article_id)
                        .first()
                    )
                    if existing:
                        existing.title = title
                        existing.content = content
                        existing.tags = tags or existing.tags
                        existing.category = category or existing.category
                        existing.article_url = article_url or existing.article_url
                        existing.article_date = article_date or existing.article_date
                        existing.article_updated = (
                            article_updated or existing.article_updated
                        )
                        existing.author = author or existing.author
                        existing.author_links = author_links or existing.author_links
                        existing.description = description or existing.description
                        existing.related_articles = (
                            related_articles or existing.related_articles
                        )
                        existing.scraped_at = datetime.utcnow()
                        session.commit()
                        return existing
                except:
                    pass
            logger.error(f"Error saving article raw: {str(e)}")
            raise
        finally:
            session.close()

    def article_raw_exists(self, article_id: str) -> bool:
        """Check if article raw exists."""
        session = self.Session()
        try:
            return (
                session.query(ArticleRaw).filter_by(article_id=article_id).first()
                is not None
            )
        finally:
            session.close()

    def author_raw_exists(
        self, author_id: Optional[str] = None, name: Optional[str] = None
    ) -> bool:
        """Check if author raw exists."""
        session = self.Session()
        try:
            if author_id:
                return (
                    session.query(AuthorRaw).filter_by(author_id=author_id).first()
                    is not None
                )
            if name:
                return session.query(AuthorRaw).filter_by(name=name).first() is not None
            return False
        finally:
            session.close()

    def clean_database(
        self, clean_authors_raw: bool = False, clean_articles_raw: bool = False
    ):
        """Clean specified raw tables from the database.

        Args:
            clean_authors_raw: If True, delete all authors_raw (default: False)
            clean_articles_raw: If True, delete all articles_raw (default: False)
        """
        logger = logging.getLogger("nzz_scraper")
        session = self.Session()

        try:
            if clean_authors_raw:
                count = session.query(AuthorRaw).count()
                session.query(AuthorRaw).delete()
                session.commit()
                logger.info(f"Cleaned authors_raw table: deleted {count} records")

            if clean_articles_raw:
                count = session.query(ArticleRaw).count()
                session.query(ArticleRaw).delete()
                session.commit()
                logger.info(f"Cleaned articles_raw table: deleted {count} records")

            if not clean_authors_raw and not clean_articles_raw:
                logger.info("No tables specified for cleaning")
        except Exception as e:
            session.rollback()
            logger.error(f"Error cleaning database: {str(e)}")
            raise
        finally:
            session.close()
