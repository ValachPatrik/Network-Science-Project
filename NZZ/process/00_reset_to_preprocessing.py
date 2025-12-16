"""00 - Reset Database to Preprocessing State

This script resets the database to preprocessing state by:
- Keeping all raw tables (authors_raw, articles_raw) intact
- Clearing all processed tables (authors, articles, related_articles, article_author_association)
- This allows reprocessing from raw data without re-scraping

Features:
- Force mode with aggressive retry logic for database locks
- Automatic cleanup of SQLite journal files (.db-journal, .db-wal, .db-shm)
- PRAGMA commands to unlock database (busy_timeout, journal_mode)
- Handles database locks with exponential backoff retry strategy
"""

import os
import sys
import time
import logging
import platform
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from sqlalchemy.exc import OperationalError

# Add parent directory to path to import database modules
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("reset_to_preprocessing")

# Raw tables to keep (DO NOT DELETE)
RAW_TABLES = {"authors_raw", "articles_raw"}

# Processed tables to clear (DELETE ALL DATA)
PROCESSED_TABLES = {
    "authors",
    "articles",
    "related_articles",
    "article_author_association",
}


class DatabaseResetter:
    """Manages database reset operations."""

    def __init__(self, db_path=None):
        """Initialize database connection.

        Args:
            db_path: Path to database file. If None, uses default path in NZZ folder.
        """
        if db_path is None:
            db_path = os.path.join(PARENT_DIR, "nzz_scraped_articles.db")
        else:
            if not os.path.isabs(db_path):
                db_path = os.path.join(PARENT_DIR, db_path)

        db_path = os.path.normpath(db_path)

        logger.info(f"Database path: {db_path}")

        # FORCE CLEANUP: Remove journal files BEFORE creating engine
        self.db_path = db_path
        self._force_remove_journal_files()

        self.engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            poolclass=NullPool,
            connect_args={
                "check_same_thread": False,
                "timeout": 30.0,  # 30 second timeout for database operations
            },
        )

        # Additional cleanup after engine creation
        self._cleanup_journal_files(force=True)

    def _force_remove_journal_files(self):
        """Forcefully remove journal files before any database operations.
        This is called BEFORE creating the engine to prevent locks."""
        journal_file = f"{self.db_path}-journal"
        wal_file = f"{self.db_path}-wal"
        shm_file = f"{self.db_path}-shm"

        files_to_remove = [journal_file, wal_file, shm_file]

        for file_path in files_to_remove:
            if os.path.exists(file_path):
                logger.warning(f"FORCE REMOVAL: Found {os.path.basename(file_path)}")
                for attempt in range(5):
                    try:
                        # On Windows, we need to handle file locks differently
                        if platform.system() == "Windows":
                            # Try to remove with retries
                            time.sleep(0.2 * (attempt + 1))
                            if os.path.exists(file_path):
                                os.chmod(file_path, 0o777)  # Make writable
                                os.remove(file_path)
                                logger.info(
                                    f"  Successfully removed {os.path.basename(file_path)} (attempt {attempt + 1})"
                                )
                                break
                        else:
                            # Unix-like systems
                            os.remove(file_path)
                            logger.info(
                                f"  Successfully removed {os.path.basename(file_path)}"
                            )
                            break
                    except PermissionError:
                        if attempt < 4:
                            logger.warning(
                                f"  Permission denied, retrying in {0.5 * (attempt + 1)} seconds... (attempt {attempt + 1}/5)"
                            )
                            time.sleep(0.5 * (attempt + 1))
                        else:
                            logger.error(
                                f"  Could not remove {os.path.basename(file_path)} after 5 attempts"
                            )
                            logger.error("  File may be locked by another process.")
                    except FileNotFoundError:
                        # File was already removed
                        break
                    except Exception as e:
                        logger.warning(
                            f"  Error removing {os.path.basename(file_path)}: {str(e)}"
                        )
                        if attempt < 4:
                            time.sleep(0.3)

    def _cleanup_journal_files(self, force=False):
        """Clean up SQLite journal files that might cause database locks.

        Args:
            force: If True, force remove journal files even if they're locked.
        """
        try:
            journal_file = f"{self.db_path}-journal"
            wal_file = f"{self.db_path}-wal"
            shm_file = f"{self.db_path}-shm"

            # Check if journal file exists
            if os.path.exists(journal_file):
                logger.warning(f"Found journal file: {journal_file}")
                logger.warning("This might indicate an incomplete transaction.")
                if force:
                    logger.warning("FORCE MODE: Attempting forced cleanup...")
                else:
                    logger.warning("Attempting to clean up...")

                try:
                    # Try to close any open connections first
                    if hasattr(self, "engine"):
                        try:
                            self.engine.dispose()
                        except Exception:
                            pass

                    if force:
                        # Force mode: wait longer and try multiple times
                        for attempt in range(3):
                            try:
                                time.sleep(1.0)  # Wait longer in force mode
                                # Try to remove with force
                                if os.path.exists(journal_file):
                                    os.remove(journal_file)
                                    logger.info(
                                        f"Journal file removed successfully (attempt {attempt + 1})."
                                    )
                                    break
                            except PermissionError:
                                if attempt < 2:
                                    logger.warning(
                                        f"Permission denied, retrying in 2 seconds... (attempt {attempt + 1}/3)"
                                    )
                                    time.sleep(2.0)
                                else:
                                    logger.error(
                                        "Could not remove journal file - file may be locked by another process."
                                    )
                                    logger.error(
                                        "Please close all database viewers and other applications using the database."
                                    )
                            except Exception as e:
                                logger.warning(f"Error removing journal file: {str(e)}")
                                if attempt < 2:
                                    time.sleep(1.0)
                    else:
                        time.sleep(0.5)  # Brief wait
                        # Remove journal file
                        os.remove(journal_file)
                        logger.info("Journal file removed successfully.")
                except Exception as e:
                    if force:
                        logger.error(
                            f"FORCE MODE: Could not remove journal file: {str(e)}"
                        )
                        logger.error("The database may be locked by another process.")
                    else:
                        logger.warning(f"Could not remove journal file: {str(e)}")
                        logger.warning(
                            "You may need to close database viewers and rerun."
                        )

            # Check for WAL files (Write-Ahead Logging mode)
            if os.path.exists(wal_file):
                logger.info(f"Found WAL file: {wal_file} (this is normal for WAL mode)")

            if os.path.exists(shm_file):
                logger.info(f"Found SHM file: {shm_file} (this is normal for WAL mode)")
        except Exception as e:
            logger.debug(f"Error checking journal files: {str(e)}")

    def get_all_tables(self):
        """Get all table names in the database."""
        with self.engine.connect() as conn:
            result = conn.execute(
                text(
                    """
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """
                )
            )
            tables = [row[0] for row in result.fetchall()]
            return tables

    def clear_table(self, table_name, force=False):
        """Clear all data from a table with retry logic for database locks.

        Args:
            table_name: Name of the table to clear
            force: If True, use more aggressive retry strategy

        Returns:
            Number of rows deleted, or 0 if failed after retries
        """
        max_retries = 10 if force else 5
        retry_delay = 1.0 if force else 2.0  # seconds
        initial_delay = 0.5 if force else 0.0

        # In force mode, try to clean up journal files before each attempt
        if force and os.path.exists(f"{self.db_path}-journal"):
            try:
                self._cleanup_journal_files(force=True)
                time.sleep(initial_delay)
            except Exception:
                pass

        for attempt in range(max_retries):
            try:
                with self.engine.connect() as conn:
                    # Try to unlock database using PRAGMA commands
                    try:
                        conn.execute(text("PRAGMA busy_timeout = 30000"))
                        # Switch from WAL mode to DELETE mode to avoid WAL locks
                        conn.execute(text("PRAGMA journal_mode = DELETE"))
                        conn.commit()
                    except Exception:
                        pass

                    # Delete all rows
                    result = conn.execute(text(f"DELETE FROM {table_name}"))
                    conn.commit()
                    deleted_count = result.rowcount
                    logger.info(f"  Cleared {table_name}: {deleted_count} rows deleted")
                    return deleted_count
            except OperationalError as e:
                if "database is locked" in str(e).lower():
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"  Database locked when clearing {table_name} (attempt {attempt + 1}/{max_retries}). Waiting {retry_delay} seconds..."
                        )
                        if force:
                            logger.warning(
                                "  FORCE MODE: Attempting to clean up journal files..."
                            )
                            try:
                                self._cleanup_journal_files(force=True)
                            except Exception:
                                pass
                        else:
                            logger.warning(
                                "  Please close any database viewers or other applications using the database."
                            )
                        time.sleep(retry_delay)
                        # Increase delay slightly for subsequent attempts
                        retry_delay = min(retry_delay * 1.2, 5.0)
                        continue
                    else:
                        logger.error(
                            f"  ERROR: Database is locked after {max_retries} attempts when clearing {table_name}"
                        )
                        if force:
                            logger.error(
                                "  FORCE MODE: Final attempt to clean up journal files..."
                            )
                            try:
                                self._cleanup_journal_files(force=True)
                                time.sleep(2.0)
                                # One more attempt after cleanup
                                with self.engine.connect() as conn:
                                    # Force unlock with PRAGMA
                                    try:
                                        conn.execute(
                                            text("PRAGMA busy_timeout = 30000")
                                        )
                                        conn.execute(
                                            text("PRAGMA journal_mode = DELETE")
                                        )
                                        conn.commit()
                                    except Exception:
                                        pass

                                    result = conn.execute(
                                        text(f"DELETE FROM {table_name}")
                                    )
                                    conn.commit()
                                    deleted_count = result.rowcount
                                    logger.info(
                                        f"  Cleared {table_name}: {deleted_count} rows deleted (after force cleanup)"
                                    )
                                    return deleted_count
                            except Exception:
                                pass
                        logger.error(
                            "  Please close any database viewers or other applications using the database."
                        )
                        logger.error("  Then rerun this script.")
                        return 0
                else:
                    logger.error(
                        f"  Database operational error when clearing {table_name}: {str(e)}"
                    )
                    return 0
            except Exception as e:
                logger.error(f"  Error clearing {table_name}: {str(e)}")
                return 0

        return 0

    def reset_to_preprocessing(self):
        """Reset database to preprocessing state.

        Clears all processed tables while keeping raw tables intact.
        """
        logger.info("=" * 80)
        logger.info("00 - Reset Database to Preprocessing State")
        logger.info("=" * 80)

        # Get all tables in database
        all_tables = self.get_all_tables()
        logger.info(f"Found {len(all_tables)} tables in database")

        # Identify tables to clear
        tables_to_clear = []
        raw_tables_found = []

        for table in all_tables:
            if table in RAW_TABLES:
                raw_tables_found.append(table)
            elif table in PROCESSED_TABLES:
                tables_to_clear.append(table)
            else:
                # Unknown table - ask user or log warning
                logger.warning(
                    f"Unknown table '{table}' - will not be cleared (not in processed tables list)"
                )

        logger.info(f"Raw tables (will be kept): {raw_tables_found}")
        logger.info(f"Processed tables (will be cleared): {tables_to_clear}")

        if not tables_to_clear:
            logger.info(
                "No processed tables found to clear. Database is already in preprocessing state."
            )
            return

        # Confirm action
        logger.info("=" * 80)
        logger.info("WARNING: This will delete all data from processed tables!")
        logger.info(f"Tables to be cleared: {', '.join(tables_to_clear)}")
        logger.info(f"Raw tables will be preserved: {', '.join(raw_tables_found)}")
        logger.info("=" * 80)

        # Clear each processed table (force mode enabled)
        total_deleted = 0
        for table in tables_to_clear:
            deleted = self.clear_table(table, force=True)
            total_deleted += deleted

        logger.info("=" * 80)
        logger.info("Reset complete!")
        logger.info("=" * 80)
        logger.info(f"Total rows deleted: {total_deleted}")
        logger.info(f"Tables cleared: {len(tables_to_clear)}")
        logger.info(f"Raw tables preserved: {len(raw_tables_found)}")
        logger.info("=" * 80)
        logger.info("Database is now in preprocessing state.")
        logger.info(
            "You can now run processing scripts starting from 01_process_impressum_authors.py"
        )
        logger.info("=" * 80)

    def close(self):
        """Close database connections and clean up."""
        try:
            if hasattr(self, "engine") and self.engine:
                # Dispose of all connections
                self.engine.dispose()
                # Wait a moment for connections to close
                time.sleep(0.2)
        except Exception as e:
            logger.warning(f"Error closing database connections: {str(e)}")

        # Final cleanup of journal files (force mode)
        try:
            self._cleanup_journal_files(force=True)
        except Exception:
            pass


def main():
    """Main function to reset database."""
    resetter = DatabaseResetter()
    try:
        resetter.reset_to_preprocessing()
    finally:
        resetter.close()


if __name__ == "__main__":
    main()
