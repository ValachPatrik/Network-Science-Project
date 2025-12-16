"""11 - Convert Unicode Escape Sequences to Characters

This script converts Unicode escape sequences (like \u00fc) to actual characters
(like ü) in the authors, locations, and departments columns.

This ensures consistency with the authors table which stores names with umlauts directly.
"""

import os
import sys
import json
import logging
from sqlalchemy import create_engine, Column, String, Text, Integer, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import NullPool

# Add parent directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("convert_unicode_escapes")

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


def process_json_field(field_value):
    """Process a JSON field to convert Unicode escapes and save with ensure_ascii=False.

    The key insight: json.loads() automatically decodes \u00fc to ü.
    But when we save, we need ensure_ascii=False to keep the actual characters.

    Args:
        field_value: JSON string from database

    Returns:
        Tuple of (parsed_list, needs_update)
        - parsed_list: List of decoded strings
        - needs_update: True if we need to save with ensure_ascii=False
    """
    if not field_value:
        return [], False

    try:
        # Parse JSON (this automatically decodes \u00fc to ü)
        parsed = (
            json.loads(field_value) if isinstance(field_value, str) else field_value
        )

        if not isinstance(parsed, list):
            return parsed, False

        # Check if any string contains non-ASCII characters
        # If they do, we need to save with ensure_ascii=False
        has_non_ascii = False
        processed_list = []

        for item in parsed:
            if isinstance(item, str):
                # Check if it has non-ASCII characters
                if any(ord(c) > 127 for c in item):
                    has_non_ascii = True
                processed_list.append(item)
            else:
                processed_list.append(item)

        # Check if the original JSON string had escapes (before parsing)
        # If it did, we definitely need to update
        had_escapes = "\\u" in str(field_value)

        needs_update = has_non_ascii or had_escapes

        return processed_list, needs_update

    except (json.JSONDecodeError, TypeError):
        return [], False


def convert_unicode_escapes():
    """Convert Unicode escape sequences to actual characters."""
    logger.info("=" * 80)
    logger.info("11 - Convert Unicode Escape Sequences to Characters")
    logger.info("=" * 80)
    logger.info("Processing authors, locations, and departments columns to:")
    logger.info("  - Convert \\u00fc -> ü, \\u00e4 -> ä, etc.")
    logger.info("  - Ensure consistency with authors table format")
    logger.info("=" * 80)

    # Initialize database manager
    processed_db = ProcessedDatabaseManager()

    try:
        Base.metadata.create_all(processed_db.engine)
        processed_session = processed_db.Session()

        try:
            # Get all articles
            logger.info("Loading articles...")
            all_articles = (
                processed_session.query(Article)
                .filter(
                    (Article.authors.isnot(None))
                    | (Article.location.isnot(None))
                    | (Article.department.isnot(None))
                )
                .all()
            )

            total_articles = len(all_articles)
            logger.info(
                f"Found {total_articles} articles with authors/locations/departments"
            )

            if total_articles == 0:
                logger.info("No articles found. Exiting.")
                return

            updated_count = 0
            converted_count = 0
            authors_converted = 0
            locations_converted = 0
            departments_converted = 0
            error_count = 0

            for article in all_articles:
                try:
                    has_changes = False

                    # Process authors
                    if article.authors:
                        try:
                            processed_authors, needs_update = process_json_field(
                                article.authors
                            )
                            if needs_update and isinstance(processed_authors, list):
                                # Always save with ensure_ascii=False if there are non-ASCII characters
                                new_json = json.dumps(
                                    processed_authors, ensure_ascii=False
                                )
                                # Only update if the JSON representation actually changed
                                if new_json != article.authors:
                                    # Log first few changes for debugging
                                    if converted_count < 3:
                                        old_preview = article.authors[:60].replace(
                                            "\n", " "
                                        )
                                        new_preview = new_json[:60].replace("\n", " ")
                                        logger.info(
                                            f"Example conversion {converted_count + 1}: Article {article.article_id}"
                                        )
                                        logger.info(f"  Before: {old_preview}...")
                                        logger.info(f"  After:  {new_preview}...")
                                    article.authors = new_json
                                    has_changes = True
                                    # Count how many authors were converted
                                    for author in processed_authors:
                                        if isinstance(author, str) and any(
                                            ord(c) > 127 for c in author
                                        ):
                                            authors_converted += 1
                        except Exception as e:
                            logger.warning(
                                f"Error processing authors for article {article.article_id}: {str(e)}"
                            )

                    # Process locations
                    if article.location:
                        try:
                            processed_locations, needs_update = process_json_field(
                                article.location
                            )
                            if needs_update and isinstance(processed_locations, list):
                                new_json = json.dumps(
                                    processed_locations, ensure_ascii=False
                                )
                                if new_json != article.location:
                                    article.location = new_json
                                    has_changes = True
                                    for location in processed_locations:
                                        if isinstance(location, str) and any(
                                            ord(c) > 127 for c in location
                                        ):
                                            locations_converted += 1
                        except Exception as e:
                            logger.warning(
                                f"Error processing locations for article {article.article_id}: {str(e)}"
                            )

                    # Process departments
                    if article.department:
                        try:
                            processed_departments, needs_update = process_json_field(
                                article.department
                            )
                            if needs_update and isinstance(processed_departments, list):
                                new_json = json.dumps(
                                    processed_departments, ensure_ascii=False
                                )
                                if new_json != article.department:
                                    article.department = new_json
                                    has_changes = True
                                    for dept in processed_departments:
                                        if isinstance(dept, str) and any(
                                            ord(c) > 127 for c in dept
                                        ):
                                            departments_converted += 1
                        except Exception as e:
                            logger.warning(
                                f"Error processing departments for article {article.article_id}: {str(e)}"
                            )

                    if has_changes:
                        converted_count += 1

                    updated_count += 1

                    # Commit every 100 records
                    if updated_count % 100 == 0:
                        try:
                            processed_session.commit()
                            logger.info(
                                f"Processed {updated_count} articles... (converted: {converted_count}, authors: {authors_converted}, locations: {locations_converted}, depts: {departments_converted})"
                            )
                        except Exception as commit_error:
                            processed_session.rollback()
                            logger.warning(
                                f"Commit error (will retry): {str(commit_error)}"
                            )

                except Exception as e:
                    error_count += 1
                    logger.error(
                        f"Error processing article {article.article_id}: {str(e)}"
                    )
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
                logger.error(
                    "Some changes may not have been saved. Please close any database viewers and rerun."
                )
                raise

            logger.info("=" * 80)
            logger.info("Processing complete!")
            logger.info("=" * 80)
            logger.info(f"Articles processed: {updated_count}")
            logger.info(f"Articles converted (had changes): {converted_count}")
            logger.info(f"Author names converted: {authors_converted}")
            logger.info(f"Location names converted: {locations_converted}")
            logger.info(f"Department names converted: {departments_converted}")
            logger.info(f"Errors: {error_count}")
            logger.info(f"Total articles: {total_articles}")
            logger.info("=" * 80)

        finally:
            processed_session.close()

    finally:
        processed_db.close()


if __name__ == "__main__":
    convert_unicode_escapes()
