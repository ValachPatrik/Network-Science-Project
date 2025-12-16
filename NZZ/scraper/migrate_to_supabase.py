"""Migrate SQLite Database to Supabase (PostgreSQL)

This script migrates the SQLite database to Supabase PostgreSQL, including:
- Schema creation (tables, indexes, constraints)
- Data migration for all tables
- Handling SQLite to PostgreSQL type conversions
"""

import os
import sys
import sqlite3
import logging
from datetime import datetime
from dotenv import load_dotenv

try:
    import psycopg2
    from psycopg2.extras import execute_batch

    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False
    print(
        "Error: psycopg2 is required. Install with: pip install psycopg2-binary python-dotenv"
    )

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("migrate_to_supabase")

# Load environment variables
load_dotenv()

# Database paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_DB_PATH = os.path.join(SCRIPT_DIR, "nzz_scraped_articles.db")

# PostgreSQL connection using Session Pooler (individual variables only)
# Session Pooler is IPv4 compatible and recommended for migrations
USER = os.getenv("user")
PASSWORD = os.getenv("password")
HOST = os.getenv("host")
PORT = os.getenv("port")
DBNAME = os.getenv("dbname")


def get_sqlite_connection():
    """Get SQLite database connection."""
    if not os.path.exists(SQLITE_DB_PATH):
        raise FileNotFoundError(f"SQLite database not found: {SQLITE_DB_PATH}")
    return sqlite3.connect(SQLITE_DB_PATH)


def get_postgres_connection():
    """Get PostgreSQL (Supabase) database connection using Session Pooler.

    Uses individual environment variables for Session Pooler connection (IPv4 compatible).
    Required .env variables:
      user=postgres.[PROJECT-REF]
      password=[YOUR-PASSWORD]
      host=aws-0-[REGION].pooler.supabase.com
      port=6543 (Session mode) or 5432 (Transaction mode)
      dbname=postgres
    """
    if not HAS_PSYCOPG2:
        raise ImportError(
            "psycopg2 is required. Install with: pip install psycopg2-binary"
        )

    # Check for required individual variables
    if not all([USER, PASSWORD, HOST, DBNAME]):
        missing = []
        if not USER:
            missing.append("user")
        if not PASSWORD:
            missing.append("password")
        if not HOST:
            missing.append("host")
        if not DBNAME:
            missing.append("dbname")

        raise ValueError(
            f"Missing required database connection parameters: {', '.join(missing)}\n"
            "Set the following in your .env file for Session Pooler:\n"
            "  user=postgres.[PROJECT-REF]\n"
            "  password=[YOUR-PASSWORD]\n"
            "  host=aws-0-[REGION].pooler.supabase.com\n"
            "  port=6543 (Session mode) or 5432 (Transaction mode)\n"
            "  dbname=postgres"
        )

    logger.info("Attempting connection to Supabase using Session Pooler:")
    logger.info(f"  host={HOST}")
    logger.info(f"  port={PORT or '5432'}")
    logger.info(f"  dbname={DBNAME}")
    logger.info(f"  user={USER}")
    try:
        conn = psycopg2.connect(
            user=USER, password=PASSWORD, host=HOST, port=PORT or "5432", dbname=DBNAME
        )
        logger.info("✓ Connected to PostgreSQL using Session Pooler")
        return conn
    except Exception as e:
        logger.error(f"✗ Failed to connect to PostgreSQL: {e}")
        raise


def test_connection():
    """Test database connection."""
    logger.info("Testing PostgreSQL connection...")
    try:
        conn = get_postgres_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        version = cursor.fetchone()
        logger.info(f"PostgreSQL version: {version[0]}")
        cursor.execute("SELECT NOW();")
        result = cursor.fetchone()
        logger.info(f"Current time: {result[0]}")
        cursor.close()
        conn.close()
        logger.info("Connection test successful!")
        return True
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        return False


def sqlite_to_postgres_type(sqlite_type):
    """Convert SQLite type to PostgreSQL type.

    Args:
        sqlite_type: SQLite column type string

    Returns:
        PostgreSQL type string
    """
    sqlite_type = sqlite_type.upper().strip()

    # Handle common SQLite types
    if "INT" in sqlite_type or "INTEGER" in sqlite_type:
        return "INTEGER"
    elif "TEXT" in sqlite_type or "VARCHAR" in sqlite_type or "CHAR" in sqlite_type:
        # Extract length if present
        if "(" in sqlite_type:
            return sqlite_type.replace("TEXT", "TEXT")
        return "TEXT"
    elif "REAL" in sqlite_type or "FLOAT" in sqlite_type or "DOUBLE" in sqlite_type:
        return "REAL"
    elif "BLOB" in sqlite_type:
        return "BYTEA"
    elif "DATETIME" in sqlite_type or "TIMESTAMP" in sqlite_type:
        return "TIMESTAMP"
    elif "DATE" in sqlite_type:
        return "DATE"
    elif "BOOLEAN" in sqlite_type or "BOOL" in sqlite_type:
        return "BOOLEAN"
    else:
        # Default to TEXT for unknown types
        return "TEXT"


def get_table_schema(sqlite_conn, table_name):
    """Get table schema from SQLite.

    Args:
        sqlite_conn: SQLite connection
        table_name: Name of the table

    Returns:
        List of (column_name, column_type, nullable, default_value, is_pk)
    """
    cursor = sqlite_conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()

    schema = []
    for col in columns:
        # PRAGMA table_info returns: (cid, name, type, notnull, dflt_value, pk)
        col_name = col[1]
        col_type = col[2]
        not_null = col[3]
        default_val = col[4]
        is_pk = col[5]

        schema.append(
            {
                "name": col_name,
                "type": sqlite_to_postgres_type(col_type),
                "not_null": bool(not_null),
                "default": default_val,
                "is_pk": bool(is_pk),
            }
        )

    return schema


def create_table_postgres(pg_conn, table_name, schema, primary_key=None):
    """Create table in PostgreSQL.

    Args:
        pg_conn: PostgreSQL connection
        table_name: Name of the table
        schema: List of column definitions
        primary_key: Primary key column name (or list for composite)
    """
    cursor = pg_conn.cursor()

    # Drop table if exists (for re-running migration)
    cursor.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE;')

    # Build CREATE TABLE statement
    columns = []
    sequences_to_create = []

    for col in schema:
        col_def = f'"{col["name"]}" {col["type"]}'

        # Handle auto-increment (SERIAL in PostgreSQL)
        # Note: We'll use INTEGER and set sequence manually to preserve IDs
        if col["is_pk"] and col["type"].upper() == "INTEGER":
            col_def = f'"{col["name"]}" INTEGER NOT NULL'
            sequences_to_create.append((table_name, col["name"]))
        else:
            if col["not_null"] or col["is_pk"]:
                col_def += " NOT NULL"
            if col["default"] is not None and col["default"] != "":
                # Handle default values
                default_val = col["default"]
                if isinstance(default_val, str):
                    # Check if it's a function call
                    if (
                        default_val.upper().startswith("CURRENT_TIMESTAMP")
                        or "NOW()" in default_val.upper()
                    ):
                        col_def += " DEFAULT CURRENT_TIMESTAMP"
                    elif default_val.isdigit():
                        col_def += f" DEFAULT {default_val}"
                    else:
                        col_def += f" DEFAULT '{default_val}'"
                else:
                    col_def += f" DEFAULT {default_val}"

        columns.append(col_def)

    create_sql = f'CREATE TABLE "{table_name}" (\n    ' + ",\n    ".join(columns)

    # Add primary key
    if primary_key:
        if isinstance(primary_key, list):
            pk_cols = ", ".join([f'"{col}"' for col in primary_key])
            create_sql += f",\n    PRIMARY KEY ({pk_cols})"
        else:
            create_sql += f',\n    PRIMARY KEY ("{primary_key}")'

    create_sql += "\n);"

    try:
        cursor.execute(create_sql)

        # Set sequence values if needed (will be done after data migration)
        pg_conn.commit()
        logger.info(f"Created table: {table_name}")
    except Exception as e:
        pg_conn.rollback()
        logger.error(f"Error creating table {table_name}: {e}")
        raise


def create_indexes_postgres(pg_conn, table_name, indexes):
    """Create indexes in PostgreSQL.

    Args:
        pg_conn: PostgreSQL connection
        table_name: Name of the table
        indexes: List of (index_name, columns, unique) tuples
    """
    cursor = pg_conn.cursor()

    for index_name, columns, is_unique in indexes:
        unique_str = "UNIQUE " if is_unique else ""
        if isinstance(columns, list):
            cols_str = ", ".join([f'"{col}"' for col in columns])
        else:
            cols_str = f'"{columns}"'

        create_index_sql = f'CREATE {unique_str}INDEX IF NOT EXISTS "{index_name}" ON "{table_name}" ({cols_str});'

        try:
            cursor.execute(create_index_sql)
            pg_conn.commit()
            logger.info(f"Created index: {index_name} on {table_name}")
        except Exception as e:
            logger.warning(f"Error creating index {index_name}: {e}")
            pg_conn.rollback()


def clean_null_bytes(value):
    """Remove NULL bytes (0x00) from string values.

    PostgreSQL doesn't allow NULL bytes in text fields.
    """
    if isinstance(value, str):
        return value.replace("\x00", "")
    elif isinstance(value, bytes):
        try:
            decoded = value.decode("utf-8")
            return decoded.replace("\x00", "")
        except Exception:
            # If decoding fails, try to remove NULL bytes from bytes
            return value.replace(b"\x00", b"")
    return value


def migrate_table_data(
    sqlite_conn, pg_conn, table_name, primary_key=None, batch_size=1000
):
    """Migrate data from SQLite to PostgreSQL.

    Args:
        sqlite_conn: SQLite connection
        pg_conn: PostgreSQL connection
        table_name: Name of the table
        primary_key: Primary key column name(s) for ON CONFLICT
        batch_size: Number of rows to insert per batch

    Returns:
        Number of rows migrated
    """
    logger.info(f"Migrating data for table: {table_name}")

    sqlite_cursor = sqlite_conn.cursor()
    pg_cursor = pg_conn.cursor()

    # Get column names
    sqlite_cursor.execute(f"PRAGMA table_info({table_name})")
    column_info = sqlite_cursor.fetchall()
    columns = [col[1] for col in column_info]

    # Use all columns (including ID) to preserve referential integrity
    columns_str = ", ".join([f'"{col}"' for col in columns])
    placeholders = ", ".join(["%s"] * len(columns))

    # Count total rows
    sqlite_cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    total_rows = sqlite_cursor.fetchone()[0]
    logger.info(f"Total rows to migrate: {total_rows:,}")

    if total_rows == 0:
        logger.info(f"No data to migrate for {table_name}")
        return 0

    # Fetch and insert data in batches (include all columns including ID)
    sqlite_cursor.execute(f"SELECT {', '.join(columns)} FROM {table_name}")

    rows_migrated = 0

    # Build ON CONFLICT clause if primary key is known
    if primary_key:
        if isinstance(primary_key, list):
            pk_cols = ", ".join([f'"{col}"' for col in primary_key])
            conflict_clause = f"ON CONFLICT ({pk_cols}) DO NOTHING"
        else:
            conflict_clause = f'ON CONFLICT ("{primary_key}") DO NOTHING'
        insert_sql = f'INSERT INTO "{table_name}" ({columns_str}) VALUES ({placeholders}) {conflict_clause}'
    else:
        # No conflict handling if no primary key specified
        insert_sql = (
            f'INSERT INTO "{table_name}" ({columns_str}) VALUES ({placeholders})'
        )

    while True:
        rows = sqlite_cursor.fetchmany(batch_size)
        if not rows:
            break

        # Convert rows to list of tuples and handle None values
        batch = []
        for row in rows:
            # Convert None to None, handle datetime objects, handle bytes, remove NULL bytes
            processed_row = []
            for val in row:
                if isinstance(val, datetime):
                    processed_row.append(val)
                elif isinstance(val, bytes):
                    # Convert bytes to string if needed
                    try:
                        decoded = val.decode("utf-8")
                        # Remove NULL bytes from decoded string
                        processed_row.append(clean_null_bytes(decoded))
                    except Exception:
                        # If decoding fails, try to clean bytes directly
                        cleaned = clean_null_bytes(val)
                        processed_row.append(cleaned)
                elif val is None:
                    processed_row.append(None)
                elif isinstance(val, str):
                    # Remove NULL bytes from strings
                    processed_row.append(clean_null_bytes(val))
                else:
                    processed_row.append(val)
            batch.append(tuple(processed_row))

        try:
            execute_batch(pg_cursor, insert_sql, batch, page_size=batch_size)
            pg_conn.commit()
            rows_migrated += len(batch)

            if rows_migrated % (batch_size * 10) == 0:
                logger.info(
                    f"Migrated {rows_migrated:,} / {total_rows:,} rows ({rows_migrated/total_rows*100:.1f}%)"
                )

        except Exception as e:
            pg_conn.rollback()
            logger.error(f"Error migrating batch for {table_name}: {e}")
            logger.error(f"SQL: {insert_sql}")
            logger.error(f"Sample row: {batch[0] if batch else 'N/A'}")
            raise

    # Reset sequence if auto-increment PK exists
    if primary_key and isinstance(primary_key, str) and rows_migrated > 0:
        try:
            pk_column = primary_key
            # Get max ID from migrated data
            pg_cursor.execute(f'SELECT MAX("{pk_column}") FROM "{table_name}"')
            max_id = pg_cursor.fetchone()[0]
            if max_id:
                # Check if sequence exists, create if not
                sequence_name = f"{table_name}_{pk_column}_seq"
                pg_cursor.execute(
                    f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_sequences WHERE sequencename = '{sequence_name}') THEN
                            CREATE SEQUENCE {sequence_name};
                        END IF;
                    END $$;
                """
                )
                # Set sequence value
                pg_cursor.execute(f"SELECT setval('{sequence_name}', {max_id}, true);")
                pg_conn.commit()
                logger.info(f"Reset sequence for {table_name}.{pk_column} to {max_id}")
        except Exception as e:
            logger.warning(f"Could not reset sequence for {table_name}: {e}")
            pg_conn.rollback()

    logger.info(f"Completed migration for {table_name}: {rows_migrated:,} rows")
    return rows_migrated


def migrate_database():
    """Main function to migrate SQLite database to Supabase."""
    logger.info("=" * 80)
    logger.info("Database Migration: SQLite to Supabase")
    logger.info("=" * 80)

    if not HAS_PSYCOPG2:
        logger.error(
            "psycopg2 is required. Install with: pip install psycopg2-binary python-dotenv"
        )
        return

    sqlite_conn = None
    pg_conn = None

    try:
        # Connect to databases
        logger.info("Connecting to SQLite database...")
        sqlite_conn = get_sqlite_connection()
        logger.info(f"Connected to SQLite: {SQLITE_DB_PATH}")

        logger.info("Connecting to Supabase...")
        pg_conn = get_postgres_connection()
        logger.info("Connected to Supabase")

        # Test connection
        test_cursor = pg_conn.cursor()
        test_cursor.execute("SELECT version();")
        version = test_cursor.fetchone()
        logger.info(f"PostgreSQL version: {version[0][:50]}...")
        test_cursor.close()

        # Get list of tables from SQLite
        sqlite_cursor = sqlite_conn.cursor()
        sqlite_cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in sqlite_cursor.fetchall()]

        logger.info(f"Found {len(tables)} tables: {', '.join(tables)}")

        # Migrate each table
        total_rows = 0

        for table_name in tables:
            logger.info("\n" + "=" * 80)
            logger.info(f"Migrating table: {table_name}")
            logger.info("=" * 80)

            try:
                # Get schema
                schema = get_table_schema(sqlite_conn, table_name)

                # Find primary key
                primary_key = None
                for col in schema:
                    if col["is_pk"]:
                        if primary_key is None:
                            primary_key = col["name"]
                        else:
                            # Composite key
                            if isinstance(primary_key, str):
                                primary_key = [primary_key, col["name"]]
                            else:
                                primary_key.append(col["name"])

                # Create table in PostgreSQL
                create_table_postgres(pg_conn, table_name, schema, primary_key)

                # Get indexes from SQLite
                sqlite_cursor.execute(
                    f"SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='{table_name}' AND sql IS NOT NULL"
                )
                indexes = []
                for idx_name, idx_sql in sqlite_cursor.fetchall():
                    if (
                        idx_name.startswith("sqlite_")
                        or "AUTOINCREMENT" in idx_sql.upper()
                    ):
                        continue  # Skip SQLite internal indexes
                    # Parse index SQL (simplified)
                    is_unique = "UNIQUE" in idx_sql.upper()
                    # Extract column names (simplified parsing)
                    if "ON" in idx_sql.upper():
                        parts = idx_sql.upper().split("ON")
                        if len(parts) > 1:
                            col_part = parts[1].split("(")[1].split(")")[0]
                            raw_cols = [
                                c.strip().strip('"').strip("'")
                                for c in col_part.split(",")
                            ]
                            # Match column names against actual schema (case-insensitive)
                            cols = []
                            for raw_col in raw_cols:
                                # Find matching column in schema (case-insensitive)
                                matched = None
                                for schema_col in schema:
                                    if schema_col["name"].upper() == raw_col.upper():
                                        matched = schema_col[
                                            "name"
                                        ]  # Use actual case from schema
                                        break
                                if matched:
                                    cols.append(matched)
                                else:
                                    # If no match, use lowercase version
                                    cols.append(raw_col.lower())
                            if cols:
                                indexes.append((idx_name, cols, is_unique))

                # Also check for unique constraints in schema
                for col in schema:
                    if col.get("is_unique", False) and not col["is_pk"]:
                        idx_name = f"{table_name}_{col['name']}_unique"
                        indexes.append((idx_name, [col["name"]], True))

                # Create indexes (after data migration for better performance)
                # Will be done after data migration

                # Migrate data
                rows = migrate_table_data(sqlite_conn, pg_conn, table_name, primary_key)
                total_rows += rows

                # Create indexes after data migration (better performance)
                if indexes:
                    create_indexes_postgres(pg_conn, table_name, indexes)

            except Exception as e:
                logger.error(f"Error migrating table {table_name}: {e}")
                logger.error("Continuing with next table...")
                continue

        # Summary
        logger.info("\n" + "=" * 80)
        logger.info("Migration Complete!")
        logger.info("=" * 80)
        logger.info(f"Tables migrated: {len(tables)}")
        logger.info(f"Total rows migrated: {total_rows:,}")
        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        if sqlite_conn:
            sqlite_conn.close()
        if pg_conn:
            pg_conn.close()
        logger.info("Database connections closed")


if __name__ == "__main__":
    import sys

    # Check for command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "--test" or sys.argv[1] == "-t":
            # Test connection only
            test_connection()
        elif sys.argv[1] == "--help" or sys.argv[1] == "-h":
            print("Usage:")
            print("  python migrate_to_supabase.py          - Run full migration")
            print("  python migrate_to_supabase.py --test    - Test connection only")
            print("  python migrate_to_supabase.py --help    - Show this help")
        else:
            logger.warning(f"Unknown argument: {sys.argv[1]}")
            logger.info("Use --help for usage information")
    else:
        # Run full migration
        migrate_database()
