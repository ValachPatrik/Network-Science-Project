"""09 - Clean Authors Final (Move Departments and Remove Text Labels)

This script performs final cleanup of the authors column:
- Moves specific department terms from authors to departments column
- Removes specific non-author items ("Text", "Text Bilder")
- Removes text labels/substrings from author names ("Text:", "Illustrationen:", etc.)

This is the final cleanup step for the authors column.
"""

import os
import sys
import json
import re
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
logger = logging.getLogger("clean_authors_final")

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


# Terms to move to departments (case-insensitive, but preserve original case)
TERMS_TO_DEPARTMENTS = {
    "nzz-bildredaktion": "NZZ-Bildredaktion",
    "feuilletonredaktion": "Feuilletonredaktion",
    "nzz-inlandredaktion": "NZZ-Inlandredaktion",
    "nzz-feuilletonredaktion": "NZZ-Feuilletonredaktion",
    "nzz redaktion": "NZZ Redaktion",
    "nzz content creation": "NZZ Content Creation",
    "die kulturredaktion": "Die Kulturredaktion",
    "nzz-nachrichtenredaktion": "NZZ-Nachrichtenredaktion",
    "kulturredaktion": "Kulturredaktion",
    "nzz bildredaktion": "NZZ Bildredaktion",
    "bildredaktion": "Bildredaktion",
    "nzz-sportredaktion": "NZZ-Sportredaktion",
    "nzz-wirtschaftsredaktion": "NZZ-Wirtschaftsredaktion",
    "nzz-visuals": "NZZ-Visuals",
    "nzz-auslandredaktion": "NZZ-Auslandredaktion",
    "feuilleton-redaktion": "Feuilleton-Redaktion",
}

# Terms to remove completely from authors (case-insensitive)
TERMS_TO_REMOVE = {"text", "text bilder"}

# Substrings to remove from author names (case-insensitive)
SUBSTRINGS_TO_REMOVE = [
    "Text:",
    "Illustrationen:",
    "Aufgezeichnet:",
    "Interview:",
    "Mitarbeit:",
]


def clean_author_name(author_string):
    """Clean an author name by removing unwanted substrings.

    Args:
        author_string: Author name string

    Returns:
        Cleaned author name, or None if should be removed
    """
    if not author_string or not isinstance(author_string, str):
        return None

    author_string = author_string.strip()

    # Check if entire string should be removed
    if author_string.lower() in TERMS_TO_REMOVE:
        return None

    # Remove unwanted substrings
    cleaned = author_string
    for substring in SUBSTRINGS_TO_REMOVE:
        # Case-insensitive removal
        cleaned = re.sub(re.escape(substring), "", cleaned, flags=re.IGNORECASE)

    cleaned = cleaned.strip()

    # If nothing left after cleaning, return None
    if not cleaned:
        return None

    return cleaned


def clean_authors_final():
    """Clean authors column by moving departments and removing unwanted items."""
    logger.info("=" * 80)
    logger.info("09 - Clean Authors Final (Move Departments and Remove Text Labels)")
    logger.info("=" * 80)
    logger.info("Processing authors column to:")
    logger.info("  - Move department terms to departments column")
    logger.info("  - Remove non-author items (Text, Text Bilder)")
    logger.info(
        "  - Remove text labels from author names (Text:, Illustrationen:, etc.)"
    )
    logger.info("=" * 80)

    # Initialize database manager
    processed_db = ProcessedDatabaseManager()

    try:
        # Create tables if they don't exist
        Base.metadata.create_all(processed_db.engine)

        processed_session = processed_db.Session()

        try:
            # Get all articles that have author data
            logger.info("Loading articles with author data...")
            all_articles = (
                processed_session.query(Article)
                .filter(Article.authors.isnot(None))
                .all()
            )

            total_articles = len(all_articles)
            logger.info(f"Found {total_articles} articles with author data")

            if total_articles == 0:
                logger.info("No articles with author data found. Exiting.")
                return

            updated_count = 0
            cleaned_count = 0
            moved_to_dept_count = 0
            removed_count = 0
            cleaned_substrings_count = 0
            error_count = 0

            for article in all_articles:
                try:
                    # Parse JSON lists
                    current_authors = []
                    current_departments = []

                    if article.authors:
                        try:
                            current_authors = (
                                json.loads(article.authors)
                                if isinstance(article.authors, str)
                                else article.authors
                            )
                        except (json.JSONDecodeError, TypeError):
                            current_authors = []

                    if article.department:
                        try:
                            current_departments = (
                                json.loads(article.department)
                                if isinstance(article.department, str)
                                else article.department
                            )
                        except (json.JSONDecodeError, TypeError):
                            current_departments = []

                    # Process authors
                    cleaned_authors = []
                    items_to_departments = []
                    items_removed = []
                    authors_cleaned = False

                    for author in current_authors:
                        if not isinstance(author, str):
                            cleaned_authors.append(author)
                            continue

                        author = author.strip()
                        if not author:
                            continue

                        # Check if it should be moved to departments
                        author_lower = author.lower()
                        if author_lower in TERMS_TO_DEPARTMENTS:
                            dept_name = TERMS_TO_DEPARTMENTS[author_lower]
                            if dept_name not in current_departments:
                                items_to_departments.append(dept_name)
                                moved_to_dept_count += 1
                            continue

                        # Check if it should be removed
                        if author_lower in TERMS_TO_REMOVE:
                            items_removed.append(author)
                            removed_count += 1
                            continue

                        # Clean substrings from author name
                        cleaned_author = clean_author_name(author)

                        if cleaned_author is None:
                            # Author was removed during cleaning
                            items_removed.append(author)
                            removed_count += 1
                            continue

                        if cleaned_author != author:
                            # Author was modified (substrings removed)
                            authors_cleaned = True
                            cleaned_substrings_count += 1

                        if cleaned_author not in cleaned_authors:
                            cleaned_authors.append(cleaned_author)

                    # Update departments if any
                    updated_departments = list(current_departments)
                    if items_to_departments:
                        for dept in items_to_departments:
                            if dept not in updated_departments:
                                updated_departments.append(dept)

                    # Check if anything changed
                    authors_changed = (
                        len(cleaned_authors) != len(current_authors)
                        or set(cleaned_authors) != set(current_authors)
                        or authors_cleaned
                    )
                    departments_changed = len(items_to_departments) > 0

                    if authors_changed or departments_changed:
                        # Update article
                        article.authors = (
                            json.dumps(cleaned_authors) if cleaned_authors else None
                        )
                        article.department = (
                            json.dumps(updated_departments)
                            if updated_departments
                            else None
                        )

                        cleaned_count += 1

                        if items_to_departments:
                            logger.debug(
                                f"Article {article.article_id}: Moved to departments: {items_to_departments}"
                            )
                        if items_removed:
                            logger.debug(
                                f"Article {article.article_id}: Removed: {items_removed}"
                            )

                    updated_count += 1

                    # Commit every 100 records
                    if updated_count % 100 == 0:
                        try:
                            processed_session.commit()
                            logger.info(
                                f"Processed {updated_count} articles... (cleaned: {cleaned_count}, moved to depts: {moved_to_dept_count}, removed: {removed_count}, cleaned substrings: {cleaned_substrings_count})"
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
            logger.info(f"Articles cleaned (had changes): {cleaned_count}")
            logger.info(f"Items moved to departments: {moved_to_dept_count}")
            logger.info(f"Items removed from authors: {removed_count}")
            logger.info(
                f"Author names cleaned (substrings removed): {cleaned_substrings_count}"
            )
            logger.info(f"Errors: {error_count}")
            logger.info(f"Total articles with author data: {total_articles}")
            logger.info("=" * 80)

        finally:
            processed_session.close()

    finally:
        processed_db.close()


if __name__ == "__main__":
    clean_authors_final()
