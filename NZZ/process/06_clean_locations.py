"""06 - Clean Locations (Remove Non-Locations and Reclassify)

This script cleans the locations column by:
- Removing non-location terms: "Text", "Bilder", "Illustrationen", "Grafik", "Interview",
  "Infografik", "Fotos", "Grafiken", "Videos", "videos", "photos", "Mitarbeit",
  "Illustration", "Video", "Texte", "Mountain View", "Infografiken"
- Moving specific terms to departments: "Bildredaktion", "NZZ-Sportredaktion"
- Moving specific terms to authors: "Michael von Ledebur", "Nadine A.", "Gioia da Silva"
- Translating country codes: "FR" -> "France"
- Cleaning leading/trailing commas: "Rom," -> "Rom"

This helps clean up misclassified data from previous extraction steps.
All operations are case-insensitive but preserve original capitalization when moving terms.
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
logger = logging.getLogger("clean_locations")

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


# Terms to remove from locations (case-insensitive)
TERMS_TO_REMOVE = {
    "text",
    "bilder",
    "illustrationen",
    "grafik",
    "interview",
    "infografik",
    "fotos",
    "grafiken",
    "videos",
    "photos",
    "mitarbeit",
    "illustration",
    "video",
    "texte",
    "mountain view",
    "infografiken",
}

# Terms to move to departments (case-insensitive, but preserve original case)
TERMS_TO_DEPARTMENTS = {
    "bildredaktion": "Bildredaktion",
    "nzz-sportredaktion": "NZZ-Sportredaktion",
}

# Terms to move to authors (case-insensitive, but preserve original case)
TERMS_TO_AUTHORS = {
    "michael von ledebur": "Michael von Ledebur",
    "nadine a.": "Nadine A.",
    "gioia da silva": "Gioia da Silva",
}

# Country code translations (case-insensitive)
COUNTRY_CODE_TRANSLATIONS = {"fr": "France"}


def clean_locations():
    """Clean locations by removing non-locations and reclassifying specific terms."""
    logger.info("=" * 80)
    logger.info("06 - Clean Locations (Remove Non-Locations and Reclassify)")
    logger.info("=" * 80)
    logger.info("Processing locations column to:")
    logger.info("  - Remove non-location terms (Text, Bilder, Illustrationen, etc.)")
    logger.info(
        "  - Move specific terms to departments (Bildredaktion, NZZ-Sportredaktion)"
    )
    logger.info("  - Move specific terms to authors (Michael von Ledebur, Nadine A.)")
    logger.info("=" * 80)

    # Initialize database manager
    processed_db = ProcessedDatabaseManager()

    try:
        # Create tables if they don't exist
        Base.metadata.create_all(processed_db.engine)

        processed_session = processed_db.Session()

        try:
            # Get all articles that have location data
            logger.info("Loading articles with location data...")
            all_articles = (
                processed_session.query(Article)
                .filter(Article.location.isnot(None))
                .all()
            )

            total_articles = len(all_articles)
            logger.info(f"Found {total_articles} articles with location data")

            if total_articles == 0:
                logger.info("No articles with location data found. Exiting.")
                return

            updated_count = 0
            cleaned_count = 0
            removed_count = 0
            moved_to_departments_count = 0
            moved_to_authors_count = 0
            error_count = 0

            for article in all_articles:
                try:
                    # Parse JSON lists
                    current_locations = []
                    current_authors = []
                    current_departments = []

                    if article.location:
                        try:
                            current_locations = (
                                json.loads(article.location)
                                if isinstance(article.location, str)
                                else article.location
                            )
                        except (json.JSONDecodeError, TypeError):
                            current_locations = []

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

                    # Process locations
                    cleaned_locations = []
                    items_removed = []
                    items_to_departments = []
                    items_to_authors = []

                    for location in current_locations:
                        if not isinstance(location, str):
                            continue

                        # Clean leading/trailing commas and whitespace
                        location_cleaned = location.strip().strip(",").strip()

                        # Skip if empty after cleaning
                        if not location_cleaned:
                            items_removed.append(location)
                            removed_count += 1
                            continue

                        location_lower = location_cleaned.lower()

                        # Check if it should be removed
                        if location_lower in TERMS_TO_REMOVE:
                            items_removed.append(location_cleaned)
                            removed_count += 1
                            continue

                        # Check if it should be moved to departments
                        if location_lower in TERMS_TO_DEPARTMENTS:
                            dept_name = TERMS_TO_DEPARTMENTS[location_lower]
                            if dept_name not in current_departments:
                                items_to_departments.append(dept_name)
                                moved_to_departments_count += 1
                            continue

                        # Check if it should be moved to authors
                        if location_lower in TERMS_TO_AUTHORS:
                            author_name = TERMS_TO_AUTHORS[location_lower]
                            if author_name not in current_authors:
                                items_to_authors.append(author_name)
                                moved_to_authors_count += 1
                            continue

                        # Translate country codes
                        if location_lower in COUNTRY_CODE_TRANSLATIONS:
                            translated = COUNTRY_CODE_TRANSLATIONS[location_lower]
                            if translated not in cleaned_locations:
                                cleaned_locations.append(translated)
                            continue

                        # Keep the cleaned location if it doesn't match any removal/move criteria
                        if location_cleaned not in cleaned_locations:
                            cleaned_locations.append(location_cleaned)

                    # Update lists
                    updated_authors = list(current_authors)
                    updated_departments = list(current_departments)

                    # Add items moved to authors
                    for author in items_to_authors:
                        if author not in updated_authors:
                            updated_authors.append(author)

                    # Add items moved to departments
                    for dept in items_to_departments:
                        if dept not in updated_departments:
                            updated_departments.append(dept)

                    # Check if anything changed
                    locations_changed = len(cleaned_locations) != len(
                        current_locations
                    ) or set(cleaned_locations) != set(current_locations)
                    authors_changed = len(items_to_authors) > 0
                    departments_changed = len(items_to_departments) > 0

                    if locations_changed or authors_changed or departments_changed:
                        # Update article
                        article.location = (
                            json.dumps(cleaned_locations) if cleaned_locations else None
                        )
                        article.authors = (
                            json.dumps(updated_authors) if updated_authors else None
                        )
                        article.department = (
                            json.dumps(updated_departments)
                            if updated_departments
                            else None
                        )

                        cleaned_count += 1

                        if items_removed:
                            logger.debug(
                                f"Article {article.article_id}: Removed from locations: {items_removed}"
                            )
                        if items_to_departments:
                            logger.debug(
                                f"Article {article.article_id}: Moved to departments: {items_to_departments}"
                            )
                        if items_to_authors:
                            logger.debug(
                                f"Article {article.article_id}: Moved to authors: {items_to_authors}"
                            )

                    updated_count += 1

                    # Commit every 100 records
                    if updated_count % 100 == 0:
                        try:
                            processed_session.commit()
                            logger.info(
                                f"Processed {updated_count} articles... (cleaned: {cleaned_count}, removed: {removed_count}, to depts: {moved_to_departments_count}, to authors: {moved_to_authors_count})"
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
            logger.info(f"Items removed from locations: {removed_count}")
            logger.info(f"Items moved to departments: {moved_to_departments_count}")
            logger.info(f"Items moved to authors: {moved_to_authors_count}")
            logger.info(f"Errors: {error_count}")
            logger.info(f"Total articles with location data: {total_articles}")
            logger.info("=" * 80)

        finally:
            processed_session.close()

    finally:
        processed_db.close()


if __name__ == "__main__":
    clean_locations()
