"""Filter related_articles to only include article_ids that exist in the articles table.

This script:
1. Loads article_id and related_articles from the articles table
2. Creates a set of all valid article_ids
3. Filters each related_articles list to only include IDs that exist
4. Creates a new column 'related_articles_filtered' with the filtered results
5. Updates the database with the new column
"""
import os
import ast
import json
import pandas as pd
import logging
from dotenv import load_dotenv

try:
    from sqlalchemy import create_engine, text
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False
    print("Error: SQLAlchemy is required. Install with: pip install sqlalchemy psycopg2-binary python-dotenv")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('filter_related_articles')

# Load environment variables
load_dotenv()


class RelatedArticlesFilter:
    """Filter related_articles to only include valid article_ids."""
    
    def __init__(self):
        """Initialize with Supabase PostgreSQL connection."""
        if not HAS_SQLALCHEMY:
            raise ImportError("SQLAlchemy is required. Install with: pip install sqlalchemy psycopg2-binary python-dotenv")
        
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
        
        # Create SQLAlchemy engine
        self.engine = self._create_engine()
    
    def _create_engine(self):
        """Create SQLAlchemy engine for PostgreSQL (Supabase) connection."""
        try:
            connection_string = (
                f"postgresql://{self.user}:{self.password}@"
                f"{self.host}:{self.port}/{self.dbname}"
            )
            engine = create_engine(
                connection_string,
                pool_pre_ping=True,
                connect_args={
                    "connect_timeout": 30,
                    "options": "-c statement_timeout=300000"  # 5 minutes
                }
            )
            return engine
        except Exception as e:
            raise ConnectionError(f"Failed to create database engine: {e}")
    
    def load_data(self, chunk_size=10000):
        """Load article_id and related_articles from the database."""
        logger.info("Loading data from articles table...")
        
        # Get total count
        count_query = "SELECT COUNT(*) FROM articles"
        total_count = pd.read_sql(count_query, self.engine).iloc[0, 0]
        logger.info(f"Total articles in database: {total_count:,}")
        
        # Load in chunks if dataset is large
        columns = "article_id, related_articles"
        chunks = []
        offset = 0
        
        while offset < total_count:
            query = (
                f"SELECT {columns} FROM articles "
                f"ORDER BY article_id "
                f"LIMIT {chunk_size} OFFSET {offset}"
            )
            logger.info(f"Loading chunk: rows {offset:,} to {min(offset + chunk_size, total_count):,}...")
            chunk_df = pd.read_sql(query, self.engine)
            if len(chunk_df) == 0:
                break
            chunks.append(chunk_df)
            offset += len(chunk_df)
            logger.info(f"  Loaded {len(chunk_df):,} rows (total: {sum(len(c) for c in chunks):,})")
        
        df = pd.concat(chunks, ignore_index=True)
        logger.info(f"Loaded {len(df):,} rows total")
        return df
    
    def create_valid_article_ids_set(self, df):
        """Create a set of all valid article_ids."""
        valid_ids = set(df['article_id'].dropna().unique())
        logger.info(f"Found {len(valid_ids):,} unique article_ids")
        return valid_ids
    
    def filter_related_articles(self, df, valid_ids):
        """Filter related_articles to only include valid article_ids."""
        logger.info("Filtering related_articles...")
        
        def filter_related(row):
            """Filter a single row's related_articles list."""
            related_articles = row['related_articles']
            
            # Handle NaN/null values
            if pd.isna(related_articles):
                return []
            
            # Parse the string/list
            try:
                if isinstance(related_articles, str):
                    parsed = ast.literal_eval(related_articles)
                elif isinstance(related_articles, list):
                    parsed = related_articles
                else:
                    return []
                
                if not isinstance(parsed, list):
                    return []
                
                # Filter to only include IDs that exist in valid_ids
                filtered = [article_id for article_id in parsed if article_id in valid_ids]
                return filtered
            except Exception as e:
                logger.warning(f"Error parsing related_articles for article_id {row['article_id']}: {e}")
                return []
        
        # Apply filtering
        df['related_articles_filtered'] = df.apply(filter_related, axis=1)
        
        # Count statistics
        total_related = 0
        for _, row in df.iterrows():
            if pd.notna(row['related_articles']):
                try:
                    if isinstance(row['related_articles'], str):
                        parsed = ast.literal_eval(row['related_articles'])
                    elif isinstance(row['related_articles'], list):
                        parsed = row['related_articles']
                    else:
                        parsed = []
                    if isinstance(parsed, list):
                        total_related += len(parsed)
                except Exception:
                    pass
        
        total_filtered = sum(len(row['related_articles_filtered']) for _, row in df.iterrows())
        removed = total_related - total_filtered
        
        logger.info("Filtering complete:")
        logger.info(f"  Total related_articles references: {total_related:,}")
        logger.info(f"  Valid references (after filtering): {total_filtered:,}")
        logger.info(f"  Removed invalid references: {removed:,}")
        if total_related > 0:
            logger.info(f"  Percentage kept: {total_filtered/total_related*100:.2f}%")
        
        return df
    
    def add_column_to_database(self):
        """Add related_articles_filtered column to the articles table if it doesn't exist."""
        logger.info("Checking if 'related_articles_filtered' column exists...")
        
        try:
            with self.engine.connect() as conn:
                # Check if column exists
                check_query = text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'articles' 
                    AND column_name = 'related_articles_filtered'
                """)
                result = conn.execute(check_query)
                column_exists = result.fetchone() is not None
                
                if not column_exists:
                    logger.info("Adding 'related_articles_filtered' column to articles table...")
                    alter_query = text("""
                        ALTER TABLE articles 
                        ADD COLUMN related_articles_filtered TEXT
                    """)
                    conn.execute(alter_query)
                    conn.commit()
                    logger.info("Column 'related_articles_filtered' added successfully")
                else:
                    logger.info("Column 'related_articles_filtered' already exists")
        except Exception as e:
            logger.error(f"Error adding column: {e}")
            raise
    
    def update_database(self, df, batch_size=1000):
        """Update the database with filtered related_articles."""
        logger.info("Updating database with filtered related_articles...")
        
        # Add column if it doesn't exist
        self.add_column_to_database()
        
        # Convert filtered lists to JSON strings for storage
        def list_to_json_string(lst):
            """Convert list to JSON string format."""
            if not lst:
                return None
            return json.dumps(lst)
        
        df['related_articles_filtered_str'] = df['related_articles_filtered'].apply(list_to_json_string)
        
        # Update in batches
        total_rows = len(df)
        updated = 0
        
        try:
            with self.engine.begin() as conn:  # Use begin() for transaction management
                for i in range(0, total_rows, batch_size):
                    batch = df.iloc[i:i + batch_size]
                    
                    for _, row in batch.iterrows():
                        article_id = row['article_id']
                        filtered_str = row['related_articles_filtered_str']
                        
                        update_query = text("""
                            UPDATE articles 
                            SET related_articles_filtered = :filtered
                            WHERE article_id = :article_id
                        """)
                        conn.execute(
                            update_query,
                            {"filtered": filtered_str, "article_id": article_id}
                        )
                    
                    updated += len(batch)
                    if updated % (batch_size * 10) == 0:
                        logger.info(f"Updated {updated:,} / {total_rows:,} rows ({updated/total_rows*100:.1f}%)")
                
                logger.info(f"Successfully updated {updated:,} rows in database")
        except Exception as e:
            logger.error(f"Error updating database: {e}")
            raise
    
    def run(self):
        """Run the complete filtering process."""
        logger.info("="*80)
        logger.info("Starting related_articles filtering process")
        logger.info("="*80)
        
        try:
            # Load data
            df = self.load_data()
            
            # Create set of valid article_ids
            valid_ids = self.create_valid_article_ids_set(df)
            
            # Filter related_articles
            df = self.filter_related_articles(df, valid_ids)
            
            # Update database
            self.update_database(df)
            
            logger.info("="*80)
            logger.info("Process completed successfully!")
            logger.info("="*80)
            
        except Exception as e:
            logger.error(f"Process failed: {e}")
            raise


if __name__ == "__main__":
    filter_processor = RelatedArticlesFilter()
    filter_processor.run()

