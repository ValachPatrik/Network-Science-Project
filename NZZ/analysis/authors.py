import logging
import os
import pandas as pd
from dotenv import load_dotenv


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("articles")

try:
    from sqlalchemy import create_engine

    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False
    print(
        "Error: SQLAlchemy is required. Install with: pip install sqlalchemy psycopg2-binary python-dotenv"
    )

# Load environment variables
load_dotenv()


class AuthorsBuilder:
    """Loads NZZ authors data, maps the authors to their resort
    """

    def __init__(self):
        """Initialize ArticleGraphBuilder with Supabase PostgreSQL connection."""
        if not HAS_SQLALCHEMY:
            raise ImportError(
                "SQLAlchemy is required. Install with: pip install sqlalchemy psycopg2-binary python-dotenv"
            )

        self.df = None
        self.components_sorted = None
        self.clusters = None  # Store clustering results

        # PostgreSQL connection parameters from environment
        self.user = os.getenv("user")
        self.password = os.getenv("password")
        self.host = os.getenv("host")
        self.port = os.getenv("port", "5432")
        self.dbname = os.getenv("dbname")

        # Validate connection parameters
        if not all([self.user, self.password, self.host, self.dbname]):
            missing = []
            if not self.user:
                missing.append("user")
            if not self.password:
                missing.append("password")
            if not self.host:
                missing.append("host")
            if not self.dbname:
                missing.append("dbname")
            raise ValueError(
                f"Missing required database connection parameters: {', '.join(missing)}\n"
                "Set the following in your .env file:\n"
                "  user=postgres.[PROJECT-REF]\n"
                "  password=[YOUR-PASSWORD]\n"
                "  host=aws-0-[REGION].pooler.supabase.com\n"
                "  port=6543 (Session mode) or 5432 (Transaction mode)\n"
                "  dbname=postgres"
            )

        # Create SQLAlchemy engine for pandas compatibility
        self.engine = self._create_engine()

    def _create_engine(self):
        """Create SQLAlchemy engine for PostgreSQL (Supabase) connection.

        Returns:
            sqlalchemy.engine.Engine: SQLAlchemy engine object
        """
        try:
            # Build connection string for SQLAlchemy
            connection_string = (
                f"postgresql://{self.user}:{self.password}@"
                f"{self.host}:{self.port}/{self.dbname}"
            )
            # Add connect_args to increase statement timeout (in milliseconds)
            # Supabase default is often 20 seconds, we'll set it higher
            engine = create_engine(
                connection_string,
                pool_pre_ping=True,
                connect_args={
                    "connect_timeout": 30,
                    "options": "-c statement_timeout=300000",  # 5 minutes in milliseconds
                },
            )
            return engine
        except Exception as e:
            raise ConnectionError(f"Failed to create database engine: {e}")
    
    def load_data(self, limit=None, chunk_size=10000):
        """Load articles from Supabase PostgreSQL into a DataFrame.

        Args:
            limit (int, optional): Maximum number of rows to load. If None, loads all rows.
            chunk_size (int): Number of rows to fetch per chunk when loading large datasets.

        Returns:
            pd.DataFrame: DataFrame containing articles
        """
        try:
            # First, try to get total count
            count_query = "SELECT COUNT(*) FROM authors"
            total_count = pd.read_sql(count_query, self.engine).iloc[0, 0]
            print(f"Total authors in database: {total_count:,}")

            if limit:
                total_to_load = min(limit, total_count)
            else:
                total_to_load = total_count

            # Only select columns we actually use: article_id, authors, related_articles_filtered
            # Use related_articles_filtered (filtered to only include valid article_ids)
            # COALESCE provides fallback to related_articles if filtered column doesn't exist
            # This significantly reduces data transfer, especially avoiding large 'content' field
            columns = "name, COALESCE(department, title) as resort"

            # If dataset is large, load in chunks
            if total_to_load > chunk_size:
                print(f"Loading {total_to_load:,} rows in chunks of {chunk_size:,}...")
                chunks = []
                offset = 0

                while offset < total_to_load:
                    current_chunk_size = min(chunk_size, total_to_load - offset)
                    query = (
                        f"SELECT {columns} FROM authors "
                        f"LIMIT {current_chunk_size} OFFSET {offset}"
                    )
                    print(
                        f"Loading chunk: rows {offset:,} to {offset + current_chunk_size:,}..."
                    )
                    chunk_df = pd.read_sql(query, self.engine)
                    if len(chunk_df) == 0:
                        break
                    chunks.append(chunk_df)
                    offset += len(chunk_df)
                    print(
                        f"  Loaded {len(chunk_df):,} rows (total: {sum(len(c) for c in chunks):,})"
                    )

                self.df = pd.concat(chunks, ignore_index=True)
            else:
                # Small dataset, load all at once
                query = f"SELECT {columns} FROM authors"
                if limit:
                    query += f" LIMIT {limit}"
                print("Loading data from Supabase...")
                self.df = pd.read_sql(query, self.engine)

            print("Columns found:", self.df.columns.tolist())
            print(f"Loaded {len(self.df)} rows.")
            return self.df
        except Exception as e:
            error_msg = str(e)
            if (
                "statement timeout" in error_msg.lower()
                or "querycanceled" in error_msg.lower()
            ):
                print("Warning: Query timed out. This might be due to a large dataset.")
                print(
                    "Consider using load_data(limit=N) to load a subset of data first."
                )
            raise ConnectionError(f"Failed to load data from database: {e}")
        

if __name__ == "__main__":
    builder = AuthorsBuilder()
    df = builder.load_data(limit=100000)  # Load up to 100,000 rows for testing
    print(df.head())