"""10 - Clean Departments (Remove NZZ Prefixes and Clean Up)

This script cleans the departments column by:
- Removing "NZZ-" prefix from department names
- Removing "NZZ " prefix from department names
- Removing " NZZ" suffix from department names
- Merging comma-separated departments
- Merging duplicate departments
- Moving author names from departments to authors column
- Removing "Illustrationen:" and moving rest to authors

Examples:
- "NZZ-Bildredaktion" -> "Bildredaktion"
- "NZZ Redaktion" -> "Redaktion"
- "Bildredaktion NZZ" -> "Bildredaktion"
- "Illustrationen: Jasmin Hegetschweiler" -> move "Jasmin Hegetschweiler" to authors
- "Matthias Sander" -> move to authors
- "Genf" -> move to authors
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
logger = logging.getLogger("clean_departments")

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


# Terms that should be moved to authors (case-insensitive)
TERMS_TO_AUTHORS = {"matthias sander": "Matthias Sander", "genf": "Genf"}

# Substrings that indicate author names in departments
AUTHOR_SUBSTRING_PREFIXES = [
    "Illustrationen:",
    "Text:",
    "Aufgezeichnet:",
    "Interview:",
    "Mitarbeit:",
]


def clean_department_name(dept_string):
    """Clean a department name by removing NZZ prefixes and suffixes.

    Args:
        dept_string: Department name string

    Returns:
        Cleaned department name, or None if empty after cleaning
    """
    if not dept_string or not isinstance(dept_string, str):
        return dept_string

    cleaned = dept_string.strip()

    # Remove "NZZ-" prefix
    if cleaned.startswith("NZZ-"):
        cleaned = cleaned[4:].strip()

    # Remove "NZZ " prefix
    if cleaned.startswith("NZZ "):
        cleaned = cleaned[4:].strip()

    # Remove " NZZ" suffix
    if cleaned.endswith(" NZZ"):
        cleaned = cleaned[:-4].strip()

    # Remove standalone "NZZ" (if the whole string is just "NZZ")
    if cleaned == "NZZ":
        cleaned = ""

    return cleaned if cleaned else None


def extract_author_from_department(dept_string):
    """Extract author name from department string if it contains author indicators.

    Args:
        dept_string: Department name string that might contain an author

    Returns:
        Tuple of (author_name, cleaned_department)
        - author_name: Author name if found, None otherwise
        - cleaned_department: Department name after removing author part, None if should be removed
    """
    if not dept_string or not isinstance(dept_string, str):
        return None, dept_string

    dept_string = dept_string.strip()

    # Check for author substring prefixes (e.g., "Illustrationen: Jasmin Hegetschweiler")
    for prefix in AUTHOR_SUBSTRING_PREFIXES:
        if prefix.lower() in dept_string.lower():
            # Find the prefix (case-insensitive)
            match = re.search(re.escape(prefix), dept_string, flags=re.IGNORECASE)
            if match:
                # Extract author name (everything after the prefix)
                author_name = dept_string[match.end() :].strip()
                if author_name:
                    # Department should be removed (it was actually an author)
                    return author_name, None

    return None, dept_string


def clean_departments():
    """Clean departments column by removing NZZ prefixes and cleaning up."""
    logger.info("=" * 80)
    logger.info("10 - Clean Departments (Remove NZZ Prefixes and Clean Up)")
    logger.info("=" * 80)
    logger.info("Processing departments column to:")
    logger.info("  - Remove 'NZZ-' prefix from department names")
    logger.info("  - Remove 'NZZ ' prefix from department names")
    logger.info("  - Remove ' NZZ' suffix from department names")
    logger.info("  - Merge comma-separated departments")
    logger.info("  - Merge duplicate departments")
    logger.info("  - Move author names to authors column")
    logger.info("=" * 80)

    # Initialize database manager
    processed_db = ProcessedDatabaseManager()

    try:
        # Create tables if they don't exist
        Base.metadata.create_all(processed_db.engine)

        processed_session = processed_db.Session()

        try:
            # Get all articles that have department data
            logger.info("Loading articles with department data...")
            all_articles = (
                processed_session.query(Article)
                .filter(Article.department.isnot(None))
                .all()
            )

            total_articles = len(all_articles)
            logger.info(f"Found {total_articles} articles with department data")

            if total_articles == 0:
                logger.info("No articles with department data found. Exiting.")
                return

            updated_count = 0
            cleaned_count = 0
            departments_cleaned = 0
            moved_to_authors_count = 0
            error_count = 0

            for article in all_articles:
                try:
                    # Parse JSON lists
                    current_departments = []
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

                    if article.authors:
                        try:
                            current_authors = (
                                json.loads(article.authors)
                                if isinstance(article.authors, str)
                                else article.authors
                            )
                        except (json.JSONDecodeError, TypeError):
                            current_authors = []

                    # Process departments
                    cleaned_departments = []
                    authors_to_add = []
                    has_changes = False

                    for dept in current_departments:
                        if not isinstance(dept, str):
                            cleaned_departments.append(dept)
                            continue

                        dept = dept.strip()
                        if not dept:
                            continue

                        # Check if it should be moved to authors
                        dept_lower = dept.lower()
                        if dept_lower in TERMS_TO_AUTHORS:
                            author_name = TERMS_TO_AUTHORS[dept_lower]
                            if author_name not in current_authors:
                                authors_to_add.append(author_name)
                                moved_to_authors_count += 1
                            has_changes = True
                            continue

                        # Check if it contains an author name (e.g., "Illustrationen: Jasmin Hegetschweiler")
                        author_name, cleaned_dept = extract_author_from_department(dept)
                        if author_name:
                            # Move to authors
                            if author_name not in current_authors:
                                authors_to_add.append(author_name)
                                moved_to_authors_count += 1
                            has_changes = True
                            # Department part is None, so skip adding it
                            continue

                        # Check if department contains comma (e.g., "Wirtschaftsredaktion, NZZ-Visuals")
                        if "," in cleaned_dept:
                            # Split by comma and clean each part
                            parts = [
                                p.strip() for p in cleaned_dept.split(",") if p.strip()
                            ]
                            for part in parts:
                                part_cleaned = clean_department_name(part)
                                if (
                                    part_cleaned
                                    and part_cleaned not in cleaned_departments
                                ):
                                    cleaned_departments.append(part_cleaned)
                                    if part_cleaned != part:
                                        has_changes = True
                                        departments_cleaned += 1
                            continue

                        # Clean the department name
                        cleaned_dept = clean_department_name(cleaned_dept)

                        if cleaned_dept != dept:
                            has_changes = True
                            departments_cleaned += 1

                        # Skip if empty after cleaning
                        if not cleaned_dept:
                            continue

                        # Add cleaned department (avoid duplicates)
                        if cleaned_dept not in cleaned_departments:
                            cleaned_departments.append(cleaned_dept)

                    # Merge similar departments (e.g., "Visuals" and "NZZ-Visuals" -> "Visuals")
                    # This handles cases where one is cleaned and becomes the same as another
                    merged_departments = []
                    for dept in cleaned_departments:
                        if not isinstance(dept, str):
                            merged_departments.append(dept)
                            continue

                        # Check if this department is already in merged list (case-insensitive)
                        dept_lower = dept.lower()
                        already_exists = any(
                            isinstance(d, str) and d.lower() == dept_lower
                            for d in merged_departments
                        )

                        if not already_exists:
                            merged_departments.append(dept)

                    cleaned_departments = merged_departments

                    # Update authors if any were found
                    updated_authors = list(current_authors)
                    if authors_to_add:
                        for author in authors_to_add:
                            if author not in updated_authors:
                                updated_authors.append(author)

                    # Check if anything changed
                    authors_changed = len(authors_to_add) > 0
                    departments_changed = has_changes or set(
                        cleaned_departments
                    ) != set(current_departments)

                    if departments_changed or authors_changed:
                        # Update article
                        article.department = (
                            json.dumps(cleaned_departments)
                            if cleaned_departments
                            else None
                        )
                        article.authors = (
                            json.dumps(updated_authors) if updated_authors else None
                        )
                        cleaned_count += 1

                    updated_count += 1

                    # Commit every 100 records
                    if updated_count % 100 == 0:
                        try:
                            processed_session.commit()
                            logger.info(
                                f"Processed {updated_count} articles... (cleaned: {cleaned_count}, depts cleaned: {departments_cleaned}, moved to authors: {moved_to_authors_count})"
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
            logger.info(f"Department names cleaned: {departments_cleaned}")
            logger.info(f"Items moved to authors: {moved_to_authors_count}")
            logger.info(f"Errors: {error_count}")
            logger.info(f"Total articles with department data: {total_articles}")
            logger.info("=" * 80)

        finally:
            processed_session.close()

    finally:
        processed_db.close()


if __name__ == "__main__":
    clean_departments()
