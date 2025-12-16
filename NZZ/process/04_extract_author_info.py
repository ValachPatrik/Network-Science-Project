"""04 - Extract Author Info (Names, Locations, Departments)

This script extracts author names, locations, and departments from the author column
in articles_raw and populates the authors, location, and department columns in the
articles table.

It uses AuthorNormalizer (with geopy, without LLM for speed) to parse author strings
and extract information, similar to how scraper v2 processes authors.

All fields are stored as JSON lists:
- authors: List of author names
- location: List of locations (split by "/" if present, e.g., "Akita/Tokio" -> ["Akita", "Tokio"])
- department: List of departments
"""

import os
import sys
import json
import logging
from sqlalchemy import create_engine, Column, String, Text, Integer, DateTime, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import NullPool

# Add parent directory to path to import database_v3 and author_normalizer
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

from database_v3 import DatabaseManagerV3, ArticleRaw
from author_normalizer import AuthorNormalizer, ParsedAuthor

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("extract_author_info")

Base = declarative_base()


class Article(Base):
    """Processed article data."""

    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(String(255), unique=True, nullable=False, index=True)
    title = Column(String(500), nullable=True)
    content = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    tags = Column(String(1000), nullable=True)
    category = Column(String(200), nullable=True)
    authors = Column(Text, nullable=True)  # JSON list of author names
    department = Column(String(200), nullable=True)  # JSON list of departments
    location = Column(String(200), nullable=True)  # JSON list of locations
    related_articles = Column(Text, nullable=True)
    article_date = Column(DateTime, nullable=True)
    article_date_updated = Column(DateTime, nullable=True)

    def __repr__(self):
        return (
            f"<Article(article_id='{self.article_id}', title='{self.title[:50]}...')>"
        )


class ProcessedDatabaseManager:
    """Manages database connection for processed tables."""

    def __init__(self, db_path=None):
        if db_path is None:
            db_path = os.path.join(PARENT_DIR, "nzz_scraped_articles.db")

        db_path = os.path.normpath(db_path)
        logger.info(f"Database path: {db_path}")

        self.engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            poolclass=NullPool,
            connect_args={"check_same_thread": False},
        )
        self.Session = scoped_session(sessionmaker(bind=self.engine))
        self.db_path = db_path

    def close(self):
        """Close database connections."""
        try:
            if hasattr(self, "Session") and self.Session:
                self.Session.remove()
            if hasattr(self, "engine") and self.engine:
                self.engine.dispose()
        except Exception as e:
            logger.warning(f"Error closing database connections: {str(e)}")


def split_location_by_slash(location_str):
    """Split location string by '/' and return list of locations.

    Args:
        location_str: Location string (e.g., "Akita/Tokio")

    Returns:
        List of location strings (e.g., ["Akita", "Tokio"])
    """
    if not location_str:
        return []

    # Split by "/" and clean each part
    locations = [loc.strip() for loc in location_str.split("/") if loc.strip()]
    return locations


def extract_author_info():
    """Extract author names, locations, and departments from author column in articles_raw."""
    logger.info("=" * 80)
    logger.info("04 - Extract Author Info (Names, Locations, Departments)")
    logger.info("=" * 80)
    logger.info(
        "Extracting author info from author strings using geopy (no LLM for speed)"
    )
    logger.info("=" * 80)

    # Initialize database managers
    raw_db = DatabaseManagerV3()
    processed_db = ProcessedDatabaseManager()

    # Initialize author normalizer WITHOUT LLM (faster, uses geopy and heuristics)
    # Try without LLM first - if geopy is available, it should work fine
    author_normalizer = AuthorNormalizer(use_geopy=True, use_llm=False)
    logger.info("AuthorNormalizer initialized (geopy only, no LLM for speed)")

    try:
        # Create tables if they don't exist
        Base.metadata.create_all(processed_db.engine)

        raw_session = raw_db.Session()
        processed_session = processed_db.Session()

        try:
            # Get all articles from articles_raw that have author information
            logger.info("Loading articles with author information from articles_raw...")
            all_raw_articles = (
                raw_session.query(ArticleRaw)
                .filter(ArticleRaw.author.isnot(None), ArticleRaw.author != "")
                .all()
            )

            total_raw_articles = len(all_raw_articles)
            logger.info(
                f"Found {total_raw_articles} articles with author information in articles_raw"
            )

            if total_raw_articles == 0:
                logger.info("No articles with author information found. Exiting.")
                return

            updated_count = 0
            skipped_count = 0
            error_count = 0
            articles_with_authors = 0
            articles_with_locations = 0
            articles_with_departments = 0

            for raw_article in all_raw_articles:
                try:
                    # Find corresponding article in processed table
                    processed_article = (
                        processed_session.query(Article)
                        .filter_by(article_id=raw_article.article_id)
                        .first()
                    )

                    if not processed_article:
                        skipped_count += 1
                        logger.debug(
                            f"Article {raw_article.article_id} not found in articles table, skipping"
                        )
                        continue

                    # Skip if all fields are already populated (don't overwrite)
                    if (
                        processed_article.authors
                        and processed_article.location
                        and processed_article.department
                    ):
                        skipped_count += 1
                        logger.debug(
                            f"Article {raw_article.article_id} already has all author info, skipping"
                        )
                        continue

                    # Extract info from author string
                    author_string = raw_article.author.strip()
                    if not author_string:
                        # No author string - skip
                        updated_count += 1  # Count as processed (no info to extract)
                        continue

                    # Use normalizer to parse author string
                    parsed_authors = author_normalizer.parse_author_string(
                        author_string
                    )

                    # Collect unique values
                    article_author_names = []
                    article_locations = []
                    article_departments = []

                    for parsed_author in parsed_authors:
                        # Collect author names (normalized names)
                        if parsed_author.normalized_name:
                            name = parsed_author.normalized_name.strip()
                            if name and name not in article_author_names:
                                article_author_names.append(name)

                        # Collect locations (split by "/" if present)
                        if parsed_author.location:
                            location = parsed_author.location.strip()

                            # Skip if empty
                            if not location:
                                continue

                            # Skip if it contains brackets or parentheses (likely not a location)
                            if (
                                "(" in location
                                or ")" in location
                                or "[" in location
                                or "]" in location
                            ):
                                logger.debug(
                                    f"Article {raw_article.article_id}: Skipping location '{location}' (contains brackets/parentheses)"
                                )
                                continue

                            # Skip if it's a department (double-check with normalizer)
                            if author_normalizer.is_department(
                                location, context=author_string
                            ):
                                logger.debug(
                                    f"Article {raw_article.article_id}: Skipping location '{location}' (identified as department)"
                                )
                                continue

                            # Skip if it looks like a name (heuristic check)
                            location_words = location.split()
                            if len(location_words) >= 2:
                                # Check if it looks like a name pattern
                                both_capitalized = all(
                                    w[0].isupper() if w else False
                                    for w in location_words[:2]
                                )
                                has_location_keyword = any(
                                    kw in location.lower()
                                    for kw in [
                                        "valley",
                                        "city",
                                        "town",
                                        "gazastreifen",
                                        "gaza",
                                        "de ",
                                        " am ",
                                        " on ",
                                        " in ",
                                        " bei ",
                                        " an ",
                                        " al-",
                                        " al ",
                                    ]
                                )

                                # If it looks like a name (both capitalized, no location indicators), skip it
                                if both_capitalized and not has_location_keyword:
                                    # Additional check: verify it's actually a location
                                    if not author_normalizer.is_location(
                                        location, context=author_string
                                    ):
                                        logger.debug(
                                            f"Article {raw_article.article_id}: Skipping location '{location}' (looks like a name, not confirmed as location)"
                                        )
                                        continue

                            # Split location by "/" (e.g., "Akita/Tokio" -> ["Akita", "Tokio"])
                            split_locations = split_location_by_slash(location)
                            for loc in split_locations:
                                if loc and loc not in article_locations:
                                    article_locations.append(loc)

                        # Collect departments
                        if parsed_author.department:
                            dept = parsed_author.department.strip()
                            if dept and dept not in article_departments:
                                article_departments.append(dept)

                    # Store as JSON lists (only update if not already set)
                    if article_author_names:
                        if not processed_article.authors:
                            processed_article.authors = json.dumps(article_author_names)
                            articles_with_authors += 1
                        logger.debug(
                            f"Article {raw_article.article_id}: Extracted authors {article_author_names} from '{author_string}'"
                        )

                    if article_locations:
                        if not processed_article.location:
                            processed_article.location = json.dumps(article_locations)
                            articles_with_locations += 1
                        logger.debug(
                            f"Article {raw_article.article_id}: Extracted locations {article_locations} from '{author_string}'"
                        )

                    if article_departments:
                        if not processed_article.department:
                            processed_article.department = json.dumps(
                                article_departments
                            )
                            articles_with_departments += 1
                        logger.debug(
                            f"Article {raw_article.article_id}: Extracted departments {article_departments} from '{author_string}'"
                        )

                    updated_count += 1

                    # Commit every 100 records
                    if updated_count % 100 == 0:
                        try:
                            processed_session.commit()
                            logger.info(
                                f"Processed {updated_count} articles... (authors: {articles_with_authors}, locations: {articles_with_locations}, departments: {articles_with_departments})"
                            )
                        except Exception as commit_error:
                            processed_session.rollback()
                            logger.warning(
                                f"Commit error (will retry): {str(commit_error)}"
                            )

                except Exception as e:
                    error_count += 1
                    logger.error(
                        f"Error processing article {raw_article.article_id}: {str(e)}"
                    )
                    try:
                        processed_session.rollback()
                    except:
                        pass
                    continue

            # Final commit
            try:
                processed_session.commit()
            except Exception as commit_error:
                processed_session.rollback()
                logger.error(f"Final commit error: {str(commit_error)}")
                logger.error(
                    "Some changes may not have been saved. Please close any database viewers and rerun."
                )
                raise

            logger.info("=" * 80)
            logger.info("Processing complete!")
            logger.info("=" * 80)
            logger.info(f"Articles processed: {updated_count}")
            logger.info(f"Articles with authors extracted: {articles_with_authors}")
            logger.info(f"Articles with locations extracted: {articles_with_locations}")
            logger.info(
                f"Articles with departments extracted: {articles_with_departments}"
            )
            logger.info(
                f"Articles skipped (not in processed table or already has info): {skipped_count}"
            )
            logger.info(f"Errors: {error_count}")
            logger.info(f"Total articles with author info in raw: {total_raw_articles}")
            logger.info("=" * 80)

        finally:
            raw_session.close()
            processed_session.close()

    finally:
        raw_db.close()
        processed_db.close()


if __name__ == "__main__":
    extract_author_info()
