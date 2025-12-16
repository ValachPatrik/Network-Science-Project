"""05 - Refine Extracted Data (Process Parentheses and Reclassify)

This script processes the extracted columns (authors, location, department) from script 04:
- If parentheses () are present, use them as natural separators
- Split content by parentheses and classify each part using AuthorNormalizer
- Reassign parts to correct columns (authors, location, department)
- Remove parentheses from final data

This helps clean up misclassified data from the initial extraction.
"""

import os
import sys
import json
import re
import logging
from sqlalchemy import create_engine, Column, String, Text, Integer, DateTime, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import NullPool

# Add parent directory to path to import author_normalizer
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

from author_normalizer import AuthorNormalizer, ParsedAuthor

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("refine_extracted_data")

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


def extract_parts_from_parentheses(text):
    """Extract parts from text using parentheses as separators.

    Args:
        text: Text string that may contain parentheses

    Returns:
        Tuple of (parts_without_parentheses, parts_inside_parentheses)
        - parts_without_parentheses: List of text parts outside parentheses
        - parts_inside_parentheses: List of text parts inside parentheses
    """
    if not text:
        return [], []

    # Find all content inside parentheses
    parts_inside = re.findall(r"\(([^)]+)\)", text)

    # Remove parentheses and their content from text
    text_without_parentheses = re.sub(r"\([^)]+\)", "", text).strip()

    # Split by common separators (comma, semicolon, etc.) and clean
    parts_without = [
        p.strip() for p in re.split(r"[,;]", text_without_parentheses) if p.strip()
    ]

    # Also clean parts inside parentheses
    parts_inside = [p.strip() for p in parts_inside if p.strip()]

    return parts_without, parts_inside


def classify_part(part, author_normalizer):
    """Classify a text part as author, location, or department.

    Args:
        part: Text part to classify
        author_normalizer: AuthorNormalizer instance

    Returns:
        Tuple of (classification_type, normalized_value)
        classification_type: 'author', 'location', 'department', or 'unknown'
        normalized_value: Normalized string value (for authors, the normalized name)
    """
    if not part or not part.strip():
        return "unknown", None

    part = part.strip()

    # First check if it's a department
    if author_normalizer.is_department(part, context=None):
        return "department", part

    # Then check if it's a location
    if author_normalizer.is_location(part, context=None):
        return "location", part

    # Try parsing as an author string
    parsed = author_normalizer.parse_author_string(part)
    if parsed and len(parsed) > 0:
        # If it parsed successfully and has a normalized name, it's an author
        if parsed[0].normalized_name and len(parsed[0].normalized_name.split()) >= 2:
            return "author", parsed[0].normalized_name

    # If we can't classify it, check if it looks like a name (heuristic)
    words = part.split()
    if len(words) >= 2:
        # Two or more words, both capitalized - likely a name
        if all(w[0].isupper() if w else False for w in words[:2]):
            # Try to normalize it
            parsed = author_normalizer.parse_author_string(part)
            if parsed and len(parsed) > 0 and parsed[0].normalized_name:
                return "author", parsed[0].normalized_name

    # Default: treat as location if single word or short
    if len(words) <= 2:
        return "location", part

    return "unknown", part


def refine_extracted_data():
    """Refine extracted data by processing parentheses and reclassifying parts."""
    logger.info("=" * 80)
    logger.info("05 - Refine Extracted Data (Process Parentheses and Reclassify)")
    logger.info("=" * 80)
    logger.info("Processing extracted columns to:")
    logger.info("  - Use parentheses as natural separators")
    logger.info("  - Reclassify parts using AuthorNormalizer")
    logger.info("  - Reassign to correct columns")
    logger.info("=" * 80)

    # Initialize database manager
    processed_db = ProcessedDatabaseManager()

    # Initialize author normalizer (same as script 04 - geopy only, no LLM for speed)
    author_normalizer = AuthorNormalizer(use_geopy=True, use_llm=False)
    logger.info("AuthorNormalizer initialized (geopy only, no LLM for speed)")

    try:
        # Create tables if they don't exist
        Base.metadata.create_all(processed_db.engine)

        processed_session = processed_db.Session()

        try:
            # Get all articles that have extracted data
            logger.info("Loading articles with extracted author info...")
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
            logger.info(f"Found {total_articles} articles with extracted data")

            if total_articles == 0:
                logger.info("No articles with extracted data found. Exiting.")
                return

            updated_count = 0
            refined_count = 0
            error_count = 0

            for article in all_articles:
                try:
                    # Parse JSON lists
                    current_authors = []
                    current_locations = []
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

                    if article.location:
                        try:
                            current_locations = (
                                json.loads(article.location)
                                if isinstance(article.location, str)
                                else article.location
                            )
                        except (json.JSONDecodeError, TypeError):
                            current_locations = []

                    if article.department:
                        try:
                            current_departments = (
                                json.loads(article.department)
                                if isinstance(article.department, str)
                                else article.department
                            )
                        except (json.JSONDecodeError, TypeError):
                            current_departments = []

                    # Check if any field contains parentheses
                    has_parentheses = False
                    all_items_to_process = []

                    # Collect all items from all fields that have parentheses
                    for item in current_authors:
                        if isinstance(item, str) and "(" in item and ")" in item:
                            has_parentheses = True
                            all_items_to_process.append(("authors", item))

                    for item in current_locations:
                        if isinstance(item, str) and "(" in item and ")" in item:
                            has_parentheses = True
                            all_items_to_process.append(("locations", item))

                    for item in current_departments:
                        if isinstance(item, str) and "(" in item and ")" in item:
                            has_parentheses = True
                            all_items_to_process.append(("departments", item))

                    if not has_parentheses:
                        # No parentheses found, skip this article
                        updated_count += 1
                        continue

                    # Process all parts and classify them
                    refined_authors = []
                    refined_locations = []
                    refined_departments = []

                    # First, keep parts that don't have parentheses (they're already classified)
                    for author in current_authors:
                        if (
                            isinstance(author, str)
                            and "(" not in author
                            and ")" not in author
                        ):
                            if author not in refined_authors:
                                refined_authors.append(author)

                    for location in current_locations:
                        if (
                            isinstance(location, str)
                            and "(" not in location
                            and ")" not in location
                        ):
                            if location not in refined_locations:
                                refined_locations.append(location)

                    for department in current_departments:
                        if (
                            isinstance(department, str)
                            and "(" not in department
                            and ")" not in department
                        ):
                            if department not in refined_departments:
                                refined_departments.append(department)

                    # Now process items with parentheses: extract parts and reclassify
                    for field_name, item in all_items_to_process:
                        # Extract parts from parentheses
                        parts_without, parts_inside = extract_parts_from_parentheses(
                            item
                        )

                        # Classify all parts (both inside and outside parentheses)
                        all_parts = parts_without + parts_inside

                        for part in all_parts:
                            if not part or not part.strip():
                                continue

                            classification, normalized_value = classify_part(
                                part, author_normalizer
                            )

                            if classification == "author" and normalized_value:
                                if normalized_value not in refined_authors:
                                    refined_authors.append(normalized_value)
                            elif classification == "location" and normalized_value:
                                if normalized_value not in refined_locations:
                                    refined_locations.append(normalized_value)
                            elif classification == "department" and normalized_value:
                                if normalized_value not in refined_departments:
                                    refined_departments.append(normalized_value)
                            elif classification == "unknown" and normalized_value:
                                # Couldn't classify - try one more time with parse_author_string
                                parsed = author_normalizer.parse_author_string(part)
                                if (
                                    parsed
                                    and len(parsed) > 0
                                    and parsed[0].normalized_name
                                ):
                                    # Looks like an author
                                    if parsed[0].normalized_name not in refined_authors:
                                        refined_authors.append(
                                            parsed[0].normalized_name
                                        )
                                else:
                                    # Default: treat as location if short
                                    if len(part.split()) <= 2:
                                        if part not in refined_locations:
                                            refined_locations.append(part)

                    # Update article with refined data
                    article.authors = (
                        json.dumps(refined_authors) if refined_authors else None
                    )
                    article.location = (
                        json.dumps(refined_locations) if refined_locations else None
                    )
                    article.department = (
                        json.dumps(refined_departments) if refined_departments else None
                    )

                    refined_count += 1
                    updated_count += 1

                    # Commit every 100 records
                    if updated_count % 100 == 0:
                        try:
                            processed_session.commit()
                            logger.info(
                                f"Processed {updated_count} articles... (refined: {refined_count})"
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
            logger.info(f"Articles refined (had parentheses): {refined_count}")
            logger.info(f"Errors: {error_count}")
            logger.info(f"Total articles with extracted data: {total_articles}")
            logger.info("=" * 80)

        finally:
            processed_session.close()

    finally:
        processed_db.close()


if __name__ == "__main__":
    refine_extracted_data()
