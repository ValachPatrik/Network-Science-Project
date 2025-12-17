"""07 - Normalize Author Names (Split and Add Commas)

This script normalizes author names in the authors column by:
- Splitting concatenated author names without commas (conservative approach)
- Adding commas between multiple authors
- Handling "und" (and) as a separator
- Moving "Bildredaktion NZZ" to departments column

Conservative splitting strategy:
- Only splits when "und" is present (clear separator)
- Only splits when AuthorNormalizer explicitly detects multiple authors
- Only attempts heuristic splitting for very long strings (6+ words)
- Prefers not splitting over incorrectly splitting a single author
- Special cases can be reviewed and handled manually

Examples:
- "Andrea Fopp und Matthias Venetz" -> "Andrea Fopp, Matthias Venetz" (has "und")
- "Bildredaktion NZZ" -> moved to departments
- "Adelheid Wölfl Chrisa Wilkens" -> only split if AuthorNormalizer detects 2 authors

Uses AuthorNormalizer to detect and parse author names.
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

from author_normalizer import AuthorNormalizer

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("normalize_author_names")

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


# Terms to move to departments (case-insensitive)
TERMS_TO_DEPARTMENTS = {"bildredaktion nzz": "Bildredaktion NZZ"}


def split_authors_string(author_string, author_normalizer):
    """Split a concatenated author string into individual authors.

    Conservative approach: Only split when we're very confident there are multiple authors.

    Args:
        author_string: String that may contain multiple concatenated authors
        author_normalizer: AuthorNormalizer instance

    Returns:
        List of normalized author names
    """
    if not author_string or not author_string.strip():
        return []

    author_string = author_string.strip()

    # Check if it should be moved to departments
    author_lower = author_string.lower()
    if author_lower in TERMS_TO_DEPARTMENTS:
        return []  # Will be handled separately

    # Strategy 1: Handle "und" (and) as separator - this is a clear indicator
    if " und " in author_string.lower():
        # Split by "und" and process each part
        parts = re.split(r"\s+und\s+", author_string, flags=re.IGNORECASE)
        all_authors = []
        for part in parts:
            part = part.strip()
            if part:
                # Try to parse this part
                parsed = author_normalizer.parse_author_string(part)
                if parsed:
                    for p in parsed:
                        if p.normalized_name:
                            all_authors.append(p.normalized_name)
                else:
                    # If parsing fails, keep as-is (don't try heuristic splitting)
                    # User can review these cases manually
                    all_authors.append(part)
        return all_authors

    # Strategy 2: Try parsing the whole string - if AuthorNormalizer detects multiple authors, use them
    parsed = author_normalizer.parse_author_string(author_string)

    # Only split if parser explicitly found multiple authors
    if parsed and len(parsed) > 1:
        # Multiple authors detected by parser - safe to split
        return [p.normalized_name for p in parsed if p.normalized_name]

    # Strategy 3: If we got one author from parser, trust it (don't try to split further)
    if parsed and len(parsed) == 1 and parsed[0].normalized_name:
        return [parsed[0].normalized_name]

    # Strategy 4: Only attempt heuristic splitting for very long strings (6+ words)
    # This is a conservative threshold to avoid splitting single authors with middle names
    words = author_string.split()
    if len(words) >= 6:
        # Very long string - might be multiple authors
        # But still be conservative - only split if we can clearly identify multiple 2-3 word names
        split_authors = split_by_name_pattern_conservative(
            author_string, author_normalizer
        )
        if len(split_authors) > 1:
            return split_authors

    # Default: return as single author (don't split)
    # User can review special cases manually
    return [author_string]


def split_by_name_pattern_conservative(text, author_normalizer):
    """Split text by detecting name patterns (very conservative approach).

    Only splits when we can clearly identify multiple complete author names.
    Prefers not splitting over incorrectly splitting a single author.

    Args:
        text: Text to split
        author_normalizer: AuthorNormalizer instance

    Returns:
        List of author names (or single-item list if can't confidently split)
    """
    if not text:
        return []

    words = text.split()
    if len(words) < 4:
        # Too short to be multiple authors - don't split
        return [text]

    # Very conservative: Only try to split if we can find at least 2 complete author names
    # An author name is typically 2-3 words

    # Strategy: Try to find a consistent pattern of 2-word or 3-word names
    # Only split if ALL segments can be validated as author names

    # Try 2-word names first (most common)
    potential_authors_2 = []
    i = 0
    while i < len(words):
        if i + 2 <= len(words):
            name_words = words[i : i + 2]
            test_string = " ".join(name_words)

            # Validate this as an author name
            parsed = author_normalizer.parse_author_string(test_string)
            if parsed and len(parsed) > 0 and parsed[0].normalized_name:
                potential_authors_2.append(parsed[0].normalized_name)
                i += 2
            else:
                # Not a valid 2-word name - try 3-word
                if i + 3 <= len(words):
                    name_words = words[i : i + 3]
                    test_string = " ".join(name_words)
                    parsed = author_normalizer.parse_author_string(test_string)
                    if parsed and len(parsed) > 0 and parsed[0].normalized_name:
                        potential_authors_2.append(parsed[0].normalized_name)
                        i += 3
                    else:
                        # Can't validate - don't split
                        return [text]
                else:
                    # Can't validate remaining - don't split
                    return [text]
        else:
            # Remaining words - try to validate as single author
            remaining = " ".join(words[i:])
            parsed = author_normalizer.parse_author_string(remaining)
            if parsed and len(parsed) > 0 and parsed[0].normalized_name:
                potential_authors_2.append(parsed[0].normalized_name)
            else:
                # Can't validate remaining - don't split
                return [text]
            break

    # Only return if we found at least 2 validated authors
    if len(potential_authors_2) >= 2:
        return potential_authors_2

    # If we couldn't confidently split, return original
    return [text]


def normalize_author_names():
    """Normalize author names by splitting concatenated names and adding commas."""
    logger.info("=" * 80)
    logger.info("07 - Normalize Author Names (Split and Add Commas)")
    logger.info("=" * 80)
    logger.info("Processing authors column to:")
    logger.info("  - Split concatenated author names")
    logger.info("  - Add commas between multiple authors")
    logger.info("  - Handle 'und' (and) as separator")
    logger.info("  - Move 'Bildredaktion NZZ' to departments")
    logger.info("=" * 80)

    # Initialize database manager
    processed_db = ProcessedDatabaseManager()

    # Initialize author normalizer
    author_normalizer = AuthorNormalizer(use_geopy=True, use_llm=False)
    logger.info("AuthorNormalizer initialized (geopy only, no LLM for speed)")

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
            normalized_count = 0
            moved_to_departments_count = 0
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
                    normalized_authors = []
                    items_to_departments = []

                    for author in current_authors:
                        if not isinstance(author, str):
                            normalized_authors.append(author)
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
                                moved_to_departments_count += 1
                            continue

                        # Check if author string already has commas (likely already normalized)
                        if "," in author:
                            # Already has commas - keep as is but ensure proper format
                            # Split by comma and normalize each part
                            parts = [p.strip() for p in author.split(",") if p.strip()]
                            for part in parts:
                                parsed = author_normalizer.parse_author_string(part)
                                if (
                                    parsed
                                    and len(parsed) > 0
                                    and parsed[0].normalized_name
                                ):
                                    if (
                                        parsed[0].normalized_name
                                        not in normalized_authors
                                    ):
                                        normalized_authors.append(
                                            parsed[0].normalized_name
                                        )
                                else:
                                    if part not in normalized_authors:
                                        normalized_authors.append(part)
                        else:
                            # No commas - try to split
                            split_authors = split_authors_string(
                                author, author_normalizer
                            )
                            for split_author in split_authors:
                                if (
                                    split_author
                                    and split_author not in normalized_authors
                                ):
                                    normalized_authors.append(split_author)

                    # Update lists
                    updated_departments = list(current_departments)

                    # Add items moved to departments
                    for dept in items_to_departments:
                        if dept not in updated_departments:
                            updated_departments.append(dept)

                    # Check if anything changed
                    authors_changed = len(normalized_authors) != len(
                        current_authors
                    ) or set(normalized_authors) != set(current_authors)
                    departments_changed = len(items_to_departments) > 0

                    if authors_changed or departments_changed:
                        # Update article
                        article.authors = (
                            json.dumps(normalized_authors)
                            if normalized_authors
                            else None
                        )
                        article.department = (
                            json.dumps(updated_departments)
                            if updated_departments
                            else None
                        )

                        normalized_count += 1

                        if items_to_departments:
                            logger.debug(
                                f"Article {article.article_id}: Moved to departments: {items_to_departments}"
                            )
                        if authors_changed:
                            logger.debug(
                                f"Article {article.article_id}: Normalized authors: {current_authors} -> {normalized_authors}"
                            )

                    updated_count += 1

                    # Commit every 100 records
                    if updated_count % 100 == 0:
                        try:
                            processed_session.commit()
                            logger.info(
                                f"Processed {updated_count} articles... (normalized: {normalized_count}, to depts: {moved_to_departments_count})"
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
            logger.info(f"Articles normalized (had changes): {normalized_count}")
            logger.info(f"Items moved to departments: {moved_to_departments_count}")
            logger.info(f"Errors: {error_count}")
            logger.info(f"Total articles with author data: {total_articles}")
            logger.info("=" * 80)

        finally:
            processed_session.close()

    finally:
        processed_db.close()


if __name__ == "__main__":
    normalize_author_names()
